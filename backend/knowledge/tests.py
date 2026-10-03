"""
Knowledge store tests: retrieval seam, local embeddings client, Qdrant Edge store,
indexing, hybrid retrieval in document Q&A, search/status/reindex API.

A real Qdrant Edge shard is used (temporary directory per test). Embeddings come
from a small deterministic "concept" embedder instead of Ollama, so the semantic
behaviour is predictable: "pump" ~ "P-101", "failure" ~ "stopped" / "tripped".
"""

import shutil
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from documents.models import Document
from documents.retrieval import Bm25Ranker, build_context, sections_fingerprint, split_sections

from . import embeddings, indexing, retrievers, store

CONCEPTS = {
    "pump": ("pump", "p-101"),
    "failure": ("failure", "failed", "stopped", "tripped"),
    "cooling": ("cooling", "fan"),
    "inspection": ("inspection", "routine"),
}


def concept_vector(text):
    low = (text or "").lower()
    return [float(sum(low.count(w) for w in words)) for words in CONCEPTS.values()] + [0.01]


def fake_embed(texts):
    return [concept_vector(t) for t in texts]


def ok_response(text):
    resp = Mock()
    resp.status_code = 200
    resp.json.return_value = {"response": text, "message": {"role": "assistant", "content": text}}
    resp.raise_for_status = Mock()
    return resp


def long_text(target_page=33, target="Night shift log: P-101 stopped working at 02:00 and the motor tripped."):
    """40 pages of filler (no word of 'pump failure') with one relevant sentence."""
    parts, offsets, pos = [], [], 0
    for page in range(1, 41):
        body = f"Page {page} report.\n" + "Routine inspection log entry for the area. " * 30
        if page == target_page:
            body += "\n\n" + target
        body += "\n\n"
        offsets.append([page, pos])
        parts.append(body)
        pos += len(body)
    return "".join(parts), offsets


class StoreTestMixin:
    """Fresh store directory + local-indexing settings + fake embedder for each test."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp(prefix="knowledge-test-")
        self.settings_override = override_settings(
            KNOWLEDGE_INDEXING=True, KNOWLEDGE_STORE_DIR=Path(self.tmp) / "store", EMBEDDING_MODEL="test-embed",
        )
        self.settings_override.enable()
        self.embed_patch = patch("knowledge.embeddings.embed", side_effect=fake_embed)
        self.embed_mock = self.embed_patch.start()

    def tearDown(self):
        store.close()
        self.embed_patch.stop()
        self.settings_override.disable()
        shutil.rmtree(self.tmp, ignore_errors=True)
        super().tearDown()

    def make_doc(self, name="doc.txt", text="Pump P-101 failure procedure.", offsets=None, **kw):
        return Document.objects.create(original_name=name, file_type=kw.pop("file_type", "TXT"),
                                       extracted_text=text, page_offsets=offsets or [], **kw)


class RetrievalSeamTests(TestCase):
    """Phase 1: build_context ranks through a pluggable ranker and reports the method."""

    def setUp(self):
        self.text = "\n\n".join(f"Section {i}: " + "filler words " * 100 for i in range(20))

    def test_default_ranker_is_bm25(self):
        _, info = build_context(self.text, "Section 7", 4000)
        self.assertEqual(info["retrieval_method"], "bm25")

    def test_custom_ranker_decides_the_sections(self):
        class LastFirst:
            def rank(self, sections, question):
                return list(reversed(range(len(sections)))), "custom"
        content, info = build_context(self.text, "anything", 4000, ranker=LastFirst())
        self.assertEqual(info["retrieval_method"], "custom")
        self.assertIn("Section 19:", content)
        self.assertNotIn("Section 10:", content)

    def test_methods_for_whole_document_and_summary(self):
        self.assertIsNone(build_context("Short.", "q", 5000)[1]["retrieval_method"])
        self.assertEqual(build_context(self.text, "", 4000)[1]["retrieval_method"], "spread")

    def test_fingerprint_tracks_text_and_section_size(self):
        self.assertEqual(sections_fingerprint("abc"), sections_fingerprint("abc"))
        self.assertNotEqual(sections_fingerprint("abc"), sections_fingerprint("abd"))
        self.assertNotEqual(sections_fingerprint("abc", size=1000), sections_fingerprint("abc"))


class EmbeddingClientTests(TestCase):
    """The embedding request stays local, on the CPU by default, and fails cleanly."""

    @override_settings(OLLAMA_URL="http://127.0.0.1:11434", EMBEDDING_MODEL="qwen3-embedding:0.6b",
                       EMBEDDING_DEVICE="cpu", EMBEDDING_BATCH_SIZE=2)
    @patch("chat.model_manager.requests.Session.post")
    def test_batches_on_cpu_through_local_ollama(self, mock_post):
        mock_post.side_effect = lambda url, json, **kw: Mock(
            status_code=200, json=Mock(return_value={"embeddings": [[0.1, 0.2]] * len(json["input"])}))
        self.assertEqual(len(embeddings.embed(["a", "b", "c"])), 3)
        self.assertEqual(mock_post.call_count, 2)
        call = mock_post.call_args_list[0]
        self.assertEqual(call.args[0], "http://127.0.0.1:11434/api/embed")
        self.assertEqual(call.kwargs["json"]["options"], {"num_gpu": 0})
        self.assertEqual(call.kwargs["json"]["model"], "qwen3-embedding:0.6b")

    @override_settings(EMBEDDING_QUERY_INSTRUCTION="Find passages")
    @patch("knowledge.embeddings.embed", return_value=[[1.0]])
    def test_query_gets_instruction_prefix(self, mock_embed):
        embeddings.embed_query("pump failure")
        self.assertEqual(mock_embed.call_args.args[0], ["Instruct: Find passages\nQuery: pump failure"])

    @override_settings(OLLAMA_URL="http://8.8.8.8:11434")
    def test_public_endpoint_is_refused(self):
        from chat.model_manager import NonLocalEndpointError
        with self.assertRaises(NonLocalEndpointError):
            embeddings.embed(["x"])

    @patch("chat.model_manager.requests.Session.post", return_value=Mock(status_code=404))
    def test_missing_model_is_explained(self, _):
        with self.assertRaisesMessage(embeddings.EmbeddingError, "not installed"):
            embeddings.embed(["x"])


class StoreTests(StoreTestMixin, TestCase):
    """Phase 2: Qdrant Edge stores sections persistently and searches them (hybrid)."""

    def points(self, texts, page=1):
        return [{"section": i, "dense": concept_vector(t), "text": t, "payload": {"page": page}}
                for i, t in enumerate(texts)]

    def test_semantic_match_without_shared_words(self):
        store.replace_document(1, self.points(["Cooling tower fan inspection complete.",
                                               "P-101 stopped working on the night shift."]))
        hits = store.search("pump failure", concept_vector("pump failure"), limit=2)
        self.assertIn("P-101 stopped working", hits[0]["text"])

    def test_identifier_in_query_boosts_the_section_naming_it(self):
        store.replace_document(1, self.points(["Pump P-2210A vibration normal.", "Pump P-2210B vibration high."]))
        hits = store.search("P-2210B vibration", concept_vector("pump"), limit=2)
        self.assertIn("P-2210B", hits[0]["text"])
        self.assertEqual((hits[0]["identifier_match"], hits[1]["identifier_match"]), (1.0, 0.0))
        self.assertEqual(store.identifiers("Was P-2210B over 7.1 mm/s per API 579?"), {"p-2210b", "7.1", "579"})

    def test_keyword_candidate_outside_dense_prefetch_is_still_found(self):
        store.replace_document(1, self.points(["Pump inspection notes."] * 5 + ["Valve XV-2201 replaced."]))
        hits = store.search("XV-2201", concept_vector("pump inspection"), limit=10, prefetch=2)
        tagged = [h for h in hits if "XV-2201" in h["text"]]
        self.assertEqual(len(tagged), 1)                    # added from the BM25 candidates ...
        self.assertIsNotNone(tagged[0]["dense_score"])      # ... with its semantic score from the shard
        self.assertEqual(tagged[0]["identifier_match"], 1.0)

    def test_one_shared_word_does_not_beat_the_semantic_match(self):
        # Regression: with dense+BM25 rank fusion, "machine" in "machine learning" outranked the pump.
        store.replace_document(1, self.points(["Machine learning model training notes.",
                                               "P-101 stopped working on the night shift."]))
        hits = store.search("pump failure of the machine", concept_vector("pump failure"), limit=1)
        self.assertIn("P-101", hits[0]["text"])

    def test_replace_filter_delete_and_persistence(self):
        store.replace_document(1, self.points(["a pump", "b pump", "c pump"]))
        store.replace_document(2, self.points(["other pump"]))
        store.replace_document(1, self.points(["only pump"]))           # replaces, not appends
        self.assertEqual((store.count(), store.count([1]), store.count([2])), (2, 1, 1))
        self.assertEqual({h["document_id"] for h in store.search("pump", concept_vector("pump"), [2])}, {2})
        store.close()                                                    # "restart"
        self.assertEqual(store.count(), 2)
        self.assertEqual(store.indexed_document_ids(), {1, 2})
        store.delete_document(1)
        self.assertEqual(store.count(), 1)

    def test_bm25_only_search_when_no_vector(self):
        store.replace_document(1, self.points(["Pump seal leak.", "Fan noise."]))
        hits = store.search("seal leak", None, limit=1)
        self.assertIn("seal", hits[0]["text"])

    def test_no_store_yet(self):
        self.assertEqual((store.count(), store.search("x", [1.0] * 5)), (0, []))
        self.assertEqual(store.info()["state"], "empty")

    def test_store_built_with_another_model_is_refused(self):
        store.replace_document(1, self.points(["pump"]))
        store.close()
        with override_settings(EMBEDDING_MODEL="other-model"):
            with self.assertRaisesMessage(store.StoreMismatchError, "--rebuild"):
                store.count()
            self.assertEqual(store.info()["state"], "unavailable")


class IndexingTests(StoreTestMixin, TestCase):

    def test_index_document_records_state(self):
        text, offsets = long_text()
        doc = self.make_doc("long.pdf", text, offsets, file_type="PDF")
        self.assertEqual(indexing.index_document(doc.id), Document.INDEX_INDEXED)
        doc.refresh_from_db()
        sections = split_sections(text, offsets)
        self.assertEqual((doc.index_chunks, doc.index_model), (len(sections), "test-embed"))
        self.assertEqual(doc.index_fingerprint, sections_fingerprint(text))
        self.assertIsNotNone(doc.indexed_at)
        self.assertEqual(store.count([doc.id]), len(sections))
        # embedded text names the document and page; the stored text is the section itself
        self.assertTrue(self.embed_mock.call_args.args[0][0].startswith("Document: long.pdf, page 1\n"))

    def test_up_to_date_index_is_not_rebuilt(self):
        doc = self.make_doc()
        indexing.index_document(doc.id)
        self.embed_mock.reset_mock()
        indexing.index_document(doc.id)
        self.embed_mock.assert_not_called()
        self.assertEqual(indexing.pending_documents(), [])

    def test_embedding_failure_keeps_document_usable(self):
        doc = self.make_doc()
        self.embed_mock.side_effect = embeddings.EmbeddingError("The local embedding model is not reachable.")
        self.assertEqual(indexing.index_document(doc.id), Document.INDEX_FAILED)
        doc.refresh_from_db()
        self.assertEqual((doc.status, doc.index_error), (Document.STATUS_READY, "The local embedding model is not reachable."))
        self.assertEqual(indexing.pending_documents(), [doc.id])

    def test_not_ready_document_is_not_indexed(self):
        doc = self.make_doc(status=Document.STATUS_PROCESSING)
        self.assertEqual(indexing.index_document(doc.id), Document.INDEX_NONE)
        self.embed_mock.assert_not_called()

    def test_deleting_a_document_removes_its_sections(self):
        keep, gone = self.make_doc("keep.txt"), self.make_doc("gone.txt")
        indexing.index_document(keep.id)
        indexing.index_document(gone.id)
        gone.delete()
        self.assertEqual(store.indexed_document_ids(), {keep.id})
        Document.objects.filter(pk=keep.id).delete()                    # queryset delete too
        self.assertEqual(store.count(), 0)

    def test_prune_orphans(self):
        doc = self.make_doc()
        indexing.index_document(doc.id)
        store.replace_document(999, [{"section": 0, "dense": concept_vector("pump"), "text": "x", "payload": {}}])
        self.assertEqual(indexing.prune_orphans(), 1)
        self.assertEqual(store.indexed_document_ids(), {doc.id})

    @override_settings(DOCUMENT_ASYNC_PROCESSING=False)
    def test_upload_is_indexed_after_extraction(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        media = tempfile.mkdtemp(dir=self.tmp)
        with override_settings(MEDIA_ROOT=media):
            r = self.client.post(reverse("document-upload"), {
                "file": SimpleUploadedFile("log.txt", b"P-101 stopped working.", content_type="text/plain")})
        self.assertEqual(r.status_code, 201)
        doc = Document.objects.get(pk=r.data["document"]["id"])
        self.assertEqual(doc.index_status, Document.INDEX_INDEXED)
        self.assertEqual(store.count([doc.id]), 1)

    @override_settings(KNOWLEDGE_INDEXING=False)
    def test_indexing_off(self):
        doc = self.make_doc()
        indexing.index_after_extraction(doc.id)
        self.embed_mock.assert_not_called()
        self.assertIsInstance(retrievers.for_document(doc), Bm25Ranker)


class HybridRetrievalTests(StoreTestMixin, APITestCase):
    """Document Q&A uses Qdrant Edge hybrid retrieval when the index is current."""

    QUESTION = "Was there a pump failure?"

    def indexed_long_doc(self):
        text, offsets = long_text()
        doc = self.make_doc("long.pdf", text, offsets, file_type="PDF", page_count=40)
        indexing.index_document(doc.id)
        doc.refresh_from_db()
        return doc

    def test_bm25_alone_misses_the_paraphrased_fact(self):
        doc = self.indexed_long_doc()
        content, info = build_context(doc.extracted_text, self.QUESTION, 6000, doc.page_offsets)
        self.assertEqual(info["retrieval_method"], "bm25")
        self.assertNotIn("P-101 stopped working", content)

    def test_hybrid_finds_the_paraphrased_fact(self):
        doc = self.indexed_long_doc()
        content, info = build_context(doc.extracted_text, self.QUESTION, 6000, doc.page_offsets,
                                      ranker=retrievers.for_document(doc))
        self.assertEqual(info["retrieval_method"], "hybrid")
        self.assertIn("P-101 stopped working", content)
        self.assertIn(33, info["pages"])

    @patch("chat.model_manager.requests.Session.post")
    def test_document_question_end_to_end(self, mock_post):
        doc = self.indexed_long_doc()
        mock_post.return_value = ok_response("Yes: P-101 stopped working at 02:00 [p. 33].")
        r = self.client.post(reverse("document-ask", kwargs={"pk": doc.id}), {"question": self.QUESTION}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["context"]["retrieval_method"], "hybrid")
        system = mock_post.call_args.kwargs["json"]["messages"][0]["content"]
        self.assertIn("[p. 33]", system)
        self.assertEqual(r.data["basis"]["warnings"], [])

    def test_stale_index_falls_back_to_bm25(self):
        doc = self.indexed_long_doc()
        doc.extracted_text += "\n\nAppendix added later."
        self.assertIsInstance(retrievers.for_document(doc), Bm25Ranker)

    def test_embedding_outage_at_question_time_falls_back_to_bm25(self):
        doc = self.indexed_long_doc()
        self.embed_mock.side_effect = embeddings.EmbeddingError("down")
        _, info = build_context(doc.extracted_text, self.QUESTION, 6000, doc.page_offsets,
                                ranker=retrievers.for_document(doc))
        self.assertEqual(info["retrieval_method"], "bm25")


class KnowledgeApiTests(StoreTestMixin, APITestCase):

    def setUp(self):
        super().setUp()
        self.pump = self.make_doc("shift_log.txt", "P-101 stopped working on the night shift.")
        self.fan = self.make_doc("tower.txt", "Cooling tower fan inspection complete.")
        for d in (self.pump, self.fan):
            indexing.index_document(d.id)

    def search(self, **body):
        return self.client.post(reverse("knowledge-search"), body, format="json")

    def test_search_across_documents(self):
        r = self.search(query="pump failure")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["method"], "hybrid")
        self.assertEqual(r.data["results"][0]["document_name"], "shift_log.txt")

    def test_search_limited_to_documents(self):
        r = self.search(query="pump failure", document_ids=[self.fan.id])
        self.assertEqual({h["document_id"] for h in r.data["results"]}, {self.fan.id})

    def test_stale_and_deleted_hits_are_dropped(self):
        Document.objects.filter(pk=self.pump.id).update(extracted_text="Rewritten text.")
        names = {h["document_name"] for h in self.search(query="pump failure").data["results"]}
        self.assertNotIn("shift_log.txt", names)

    def test_search_without_embedding_model_uses_bm25(self):
        self.embed_mock.side_effect = embeddings.EmbeddingError("down")
        r = self.search(query="cooling tower")
        self.assertEqual((r.data["method"], r.data["results"][0]["document_name"]), ("bm25", "tower.txt"))

    def test_search_validation(self):
        self.assertEqual(self.search(query="  ").status_code, 400)
        self.assertEqual(self.search(query="x" * 1001).status_code, 400)
        self.assertEqual(self.search(query="x", limit="many").status_code, 400)

    def test_status(self):
        Document.objects.create(original_name="new.txt", file_type="TXT", extracted_text="Unindexed text.")
        r = self.client.get(reverse("knowledge-status"))
        self.assertEqual(r.data["store"]["points"], 2)
        self.assertEqual(r.data["store"]["state"], "ready")
        self.assertEqual((r.data["documents"]["indexed"], r.data["documents"]["needs_indexing"]), (2, 1))

    @patch("documents.jobs.submit_index")
    def test_reindex_queues_only_out_of_date_documents(self, mock_submit):
        new = Document.objects.create(original_name="new.txt", file_type="TXT", extracted_text="Unindexed text.")
        r = self.client.post(reverse("knowledge-reindex"), {}, format="json")
        self.assertEqual((r.status_code, r.data["document_ids"]), (202, [new.id]))
        r = self.client.post(reverse("knowledge-reindex"), {"force": True}, format="json")
        self.assertEqual(r.data["queued"], 3)
        mock_submit.assert_called_with(r.data["document_ids"], force=True)

    @override_settings(KNOWLEDGE_INDEXING=False)
    def test_reindex_when_disabled(self):
        self.assertEqual(self.client.post(reverse("knowledge-reindex"), {}, format="json").status_code, 409)
