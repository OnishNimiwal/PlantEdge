"""
Phase 3 (shared knowledge base) and Phase 4 (classification + confidentiality) tests.

Same fixtures as tests.py: a real Qdrant Edge shard in a temporary directory and the
deterministic concept embedder; the chat model is mocked at the HTTP layer.
"""

import json
import tempfile
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from chat.models import Conversation
from documents.models import Document
from documents.retrieval import build_context, headings, split_sections

from . import indexing, policy, sensitivity, store
from .models import PolicyEvent
from .qa import CONFIDENTIAL_NOTICE, NO_CITATION, retrieval_query
from .tests import StoreTestMixin, ok_response

SHIFT_LOG = "\n\n".join(
    [f"Shift log, 2026-09-{d:02d}, unit CDU-2.\n" + "Rounds completed. Lube oil levels normal. " * 30
     for d in range(20, 24)]
    + ["At 02:10 the operator found P-101 had stopped working; the motor tripped on overload."]
)


class SectionHeadingTests(TestCase):
    """Phase 3: a section that continues an earlier entry keeps that entry's heading."""

    def test_continuation_section_gets_the_heading_before_it(self):
        sections = split_sections(SHIFT_LOG)
        target = next(s for s in sections if "P-101 had stopped" in s["text"])
        self.assertEqual(target["heading"], "Shift log, 2026-09-23, unit CDU-2.")

    def test_section_opening_with_its_own_heading_has_none(self):
        sections = split_sections(SHIFT_LOG)
        self.assertIsNone(sections[0]["heading"])
        self.assertTrue(all(s["heading"] is None for s in sections if s["text"].startswith("Shift log")))

    def test_wrapped_prose_and_page_markers_are_not_headings(self):
        self.assertEqual(headings("External corrosion observed on shell near\nthe south saddle support."), [])
        self.assertEqual(headings("--- Page 2 (OCR) ---\nEquipment: Pump"), [])
        self.assertEqual([h for _, h in headings("INSPECTION REPORT\n\n# Findings\nShell corrosion.")],
                         ["INSPECTION REPORT", "# Findings"])

    def test_prompt_shows_the_heading_as_context(self):
        content, _ = build_context(SHIFT_LOG, "What happened to P-101?", 2500)
        # the section holding "At 02:10" is introduced by its log entry's date line
        self.assertIn("(context: Shift log, 2026-09-23, unit CDU-2.)\n", content.split("At 02:10")[0])


class KnowledgeQATests(StoreTestMixin, APITestCase):
    """Phase 3: questions answered from all indexed documents, with checked [S#] citations."""

    def setUp(self):
        super().setUp()
        self.log = self.make_doc("shift_log.txt", "P-101 stopped working at 02:10; motor tripped on overload.")
        self.tower = self.make_doc("tower.txt", "Cooling tower fan inspection complete. Fan speed 140 rpm.")
        for d in (self.log, self.tower):
            indexing.index_document(d.id)

    def ask(self, **body):
        return self.client.post(reverse("knowledge-ask"), body, format="json")

    @patch("chat.model_manager.requests.Session.post")
    def test_answer_from_the_knowledge_base(self, mock_post):
        mock_post.return_value = ok_response("P-101 stopped working at 02:10 [S1].")
        r = self.ask(question="Was there a pump failure?")
        self.assertEqual(r.status_code, 200)
        system = mock_post.call_args.kwargs["json"]["messages"][0]["content"]
        self.assertIn("[S1] shift_log.txt · internal\nP-101 stopped working", system)
        # knowledge-base instructions ask for [S#] labels, not the page citations of document Q&A
        self.assertIn("such as [S1]", system)
        self.assertNotIn("cite the page as [p. N]", system)
        self.assertEqual(r.data["sources"][0]["document_name"], "shift_log.txt")
        self.assertEqual(r.data["context"]["retrieval_method"], "hybrid")
        self.assertEqual(r.data["basis"]["type"], "knowledge")
        self.assertEqual(r.data["basis"]["detail"], "shift_log.txt")
        self.assertEqual(r.data["basis"]["warnings"], [])
        conv = Conversation.objects.get(pk=r.data["conversation_id"])
        self.assertEqual((conv.kind, conv.document_id), (Conversation.KIND_KNOWLEDGE, None))

    @patch("chat.model_manager.requests.Session.post")
    def test_checks_on_the_answer(self, mock_post):
        mock_post.return_value = ok_response("The pump stopped at 03:45 [S9].")
        w = self.ask(question="Was there a pump failure?").data["basis"]["warnings"]
        self.assertIn("Values not found in the sources: 3, 45", w)
        self.assertIn("Cited source not given to the model: S9", w)
        mock_post.return_value = ok_response("The pump stopped.")
        self.assertIn(NO_CITATION, self.ask(question="Was there a pump failure?").data["basis"]["warnings"])

    @patch("chat.model_manager.requests.Session.post")
    def test_miscited_statement_is_flagged(self, mock_post):
        # Live case: a fact from the tower report credited to the shift log.
        mock_post.return_value = ok_response("Fan inspection complete, fan speed 140 rpm [S1].")
        r = self.ask(question="Was there a pump failure?")
        self.assertEqual(r.data["sources"][0]["document_name"], "shift_log.txt")
        self.assertIn("A statement cited to S1 matches S2 better: check the citation", r.data["basis"]["warnings"])
        self.assertEqual([s["cited"] for s in r.data["sources"]], [True, False])

    def test_miscitation_heuristic(self):
        from .qa import miscited
        doc = lambda text: {"hit": {"text": text, "heading": None}}  # noqa: E731
        sources = [doc("P-101 stopped; maintenance notified."), doc("Before restarting, maintenance checks motor and coupling.")]
        self.assertEqual(miscited("Maintenance must check the motor and coupling [S1].", sources), [("S1", "S2")])
        self.assertEqual(miscited("Maintenance must check the motor and coupling [S2].", sources), [])
        self.assertEqual(miscited("It stopped [S1].", sources), [])          # too short to judge

    @patch("chat.model_manager.requests.Session.post")
    def test_source_labels_are_not_read_as_values(self, mock_post):
        mock_post.return_value = ok_response("Fan speed 140 rpm [S2] and P-101 tripped [S1].")
        self.assertEqual(self.ask(question="fan and pump status?").data["basis"]["warnings"], [])

    @patch("chat.model_manager.requests.Session.post")
    def test_confidential_source_adds_a_handling_notice(self, mock_post):
        policy.change_classification(self.log, Document.CLASS_CONFIDENTIAL)
        mock_post.return_value = ok_response("P-101 stopped working at 02:10 [S1].")
        r = self.ask(question="Was there a pump failure?")
        self.assertIn("[S1] shift_log.txt · confidential", mock_post.call_args.kwargs["json"]["messages"][0]["content"])
        self.assertIn(CONFIDENTIAL_NOTICE, r.data["basis"]["warnings"])

    @patch("chat.model_manager.requests.Session.post")
    def test_follow_up_is_searched_with_the_previous_question(self, mock_post):
        mock_post.return_value = ok_response("P-101 stopped [S1].")
        conv_id = self.ask(question="Was there a pump failure last night?").data["conversation_id"]
        r = self.ask(question="Which motor?", conversation_id=conv_id)
        self.assertEqual(r.data["context"]["retrieval_query"], "Was there a pump failure last night?\nWhich motor?")
        conv = Conversation.objects.get(pk=conv_id)
        self.assertEqual(retrieval_query(conv, "A long, self-contained question about the cooling tower fan"),
                         "A long, self-contained question about the cooling tower fan")

    @patch("chat.model_manager.requests.Session.post")
    def test_regenerate_and_document_filter(self, mock_post):
        mock_post.return_value = ok_response("first [S1]")
        conv_id = self.ask(question="Was there a pump failure?").data["conversation_id"]
        mock_post.return_value = ok_response("second [S1]")
        r = self.ask(regenerate=True, conversation_id=conv_id)
        self.assertEqual(r.data["answer"], "second [S1]")
        self.assertEqual(Conversation.objects.get(pk=conv_id).messages.count(), 2)
        r = self.ask(question="Was there a pump failure?", document_ids=[self.tower.id])
        self.assertEqual({s["document_id"] for s in r.data["sources"]}, {self.tower.id})

    def test_regenerate_needs_an_existing_knowledge_conversation(self):
        chat = Conversation.objects.create(title="chat")
        self.assertEqual(self.ask(regenerate=True, conversation_id=str(chat.id)).status_code, 400)

    @patch("chat.model_manager.requests.Session.post")
    def test_stream(self, mock_post):
        from chat.tests import ollama_stream
        mock_post.return_value = ollama_stream("P-101 stopped ", "[S1].")
        r = self.client.post(reverse("knowledge-ask-stream"), {"question": "Was there a pump failure?"}, format="json")
        events = [json.loads(line) for line in b"".join(r.streaming_content).decode().splitlines() if line]
        self.assertEqual(events[0]["type"], "start")
        self.assertEqual(events[0]["sources"][0]["document_name"], "shift_log.txt")
        self.assertEqual((events[-1]["type"], events[-1]["answer"]), ("done", "P-101 stopped [S1]."))
        self.assertEqual(events[-1]["basis"]["type"], "knowledge")

    @patch("chat.model_manager.requests.Session.post")
    def test_conversation_lists_keep_kinds_apart(self, mock_post):
        mock_post.return_value = ok_response("answer [S1]")
        kb = self.ask(question="Was there a pump failure?").data["conversation_id"]
        url = reverse("conversation-list")
        ids = lambda **q: {c["id"] for c in self.client.get(url, q).data["conversations"]}  # noqa: E731
        self.assertEqual(ids(kind="knowledge"), {kb})
        self.assertNotIn(kb, ids())
        self.assertNotIn(kb, ids(scope="all"))

    def test_validation(self):
        self.assertEqual(self.ask().status_code, 400)
        self.assertEqual(self.ask(question="x", document_ids=["a"]).status_code, 400)


class SensitivityScanTests(TestCase):
    """Phase 4: the content scan finds sensitive content and never returns the values."""

    def kinds(self, text):
        return {m["label"] for m in sensitivity.scan(text)}

    def test_findings(self):
        text = ("CONFIDENTIAL - contact r.shetty@mrpl.example or +91 98450 12345. PAN ABCDE1234F, "
                "Aadhaar 2345 6789 0123. password: hunter2. DCS gateway 10.20.4.17.\n"
                "-----BEGIN RSA PRIVATE KEY-----")
        self.assertEqual(self.kinds(text), {
            "Confidentiality marking", "Email address", "Phone number", "PAN number", "Aadhaar number",
            "Password or secret", "Internal network address", "Private key"})
        dumped = json.dumps(sensitivity.scan(text))
        for secret in ("r.shetty", "98450", "ABCDE1234F", "hunter2", "10.20.4.17"):
            self.assertNotIn(secret, dumped)

    def test_phone_at_sentence_end_but_not_decimals(self):
        self.assertEqual(self.kinds("Call 98450 12345."), {"Phone number"})
        self.assertEqual(self.kinds("Flow 98450.12345 m3/h"), set())

    def test_ordinary_plant_text_is_clean(self):
        text = ("Report No: INS-2026-0417, 14 September 2026. Pump P-2210B vibration 7.8 mm/s (limit 7.1). "
                "Wall thickness 7.2 mm; API 579 assessment if below 6.5 mm. WO-55812. Version 1.2.3.4 of the SOP.")
        self.assertEqual(sensitivity.scan(text), [])

    def test_levels(self):
        self.assertEqual(policy.required_level(sensitivity.scan("gateway 192.168.1.20")), Document.CLASS_INTERNAL)
        self.assertEqual(policy.required_level(sensitivity.scan("Internal use only")), Document.CLASS_CONFIDENTIAL)
        self.assertIsNone(policy.required_level([]))


class ClassificationTests(StoreTestMixin, APITestCase):
    """Phase 4: levels at upload, automatic escalation, and the rules for changing a level."""

    def upload(self, text, **extra):
        media = tempfile.mkdtemp(dir=self.tmp)
        with override_settings(MEDIA_ROOT=media, DOCUMENT_ASYNC_PROCESSING=False):
            r = self.client.post(reverse("document-upload"), {
                "file": SimpleUploadedFile("f.txt", text.encode(), content_type="text/plain"), **extra})
        self.assertEqual(r.status_code, 201, r.data)
        return Document.objects.get(pk=r.data["document"]["id"])

    def events(self, doc):
        return list(PolicyEvent.objects.filter(document=doc).order_by("id").values_list("event", flat=True))

    def test_default_level_is_internal(self):
        doc = self.upload("Pump P-101 routine inspection.")
        self.assertEqual((doc.classification, doc.classification_source), ("internal", "default"))
        self.assertEqual(self.events(doc), ["classified"])

    def test_chosen_level_and_index_payload(self):
        doc = self.upload("Pump P-101 routine inspection.", classification="shareable")
        self.assertEqual((doc.classification, doc.classification_source), ("shareable", "user"))
        self.assertEqual({p["classification"] for p in store.scroll_sections([doc.id])}, {"shareable"})

    def test_content_scan_raises_the_level(self):
        doc = self.upload("Pump P-101 inspected. Contact: r.shetty@mrpl.example", classification="shareable")
        self.assertEqual((doc.classification, doc.classification_source), ("confidential", "detected"))
        self.assertEqual(doc.sensitivity_markers[0]["label"], "Email address")
        self.assertEqual(self.events(doc), ["classified", "auto_escalated"])
        self.assertEqual({p["classification"] for p in store.scroll_sections([doc.id])}, {"confidential"})

    def test_scan_never_lowers_a_level(self):
        doc = self.upload("Plain text.", classification="confidential")
        self.assertEqual(doc.classification, "confidential")

    def test_invalid_level_at_upload(self):
        r = self.client.post(reverse("document-upload"), {
            "file": SimpleUploadedFile("f.txt", b"x", content_type="text/plain"), "classification": "secret"})
        self.assertEqual(r.status_code, 400)

    def change(self, doc, **body):
        return self.client.post(reverse("document-classification", kwargs={"pk": doc.id}), body, format="json")

    def test_raise_and_lower_with_reason(self):
        doc = self.upload("Pump P-101 routine inspection.")
        self.assertEqual(self.change(doc, classification="confidential").status_code, 200)
        r = self.change(doc, classification="shareable")
        self.assertEqual(r.status_code, 400)
        self.assertIn("reason", r.data["error"])
        r = self.change(doc, classification="shareable", reason="Generic SOP, approved for sharing")
        self.assertEqual((r.status_code, r.data["document"]["classification"]), (200, "shareable"))
        self.assertEqual({p["classification"] for p in store.scroll_sections([doc.id])}, {"shareable"})
        last = PolicyEvent.objects.filter(document=doc).first()
        self.assertEqual((last.event, last.from_level, last.to_level, last.client),
                         ("changed", "confidential", "shareable", "127.0.0.1"))

    def test_lowering_below_the_scanned_level_is_refused(self):
        doc = self.upload("Call 98450 12345 for the permit.")
        r = self.change(doc, classification="shareable", reason="needed", override=True)
        self.assertEqual(r.status_code, 403)
        self.assertIn("Phone number", r.data["error"])
        doc.refresh_from_db()
        self.assertEqual(doc.classification, "confidential")
        self.assertEqual(self.events(doc)[-1], "change_refused")

    @override_settings(CLASSIFICATION_ALLOW_OVERRIDE=True)
    def test_override_when_the_site_allows_it(self):
        doc = self.upload("Call 98450 12345 for the permit.")
        self.assertEqual(self.change(doc, classification="shareable", reason="x").status_code, 403)  # no flag
        r = self.change(doc, classification="shareable", reason="Helpdesk number is public", override=True)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(PolicyEvent.objects.filter(document=doc).first().detail["override"])

    def test_unknown_level(self):
        doc = self.upload("x y z")
        self.assertEqual(self.change(doc, classification="top-secret").status_code, 400)

    def test_policy_and_events_api(self):
        doc = self.upload("Pump P-101.")
        levels = self.client.get(reverse("knowledge-policy")).data
        self.assertEqual([lv["id"] for lv in levels["levels"]], ["public", "shareable", "internal", "confidential"])
        self.assertEqual([lv["may_leave_site"] for lv in levels["levels"]], [True, True, False, False])
        self.assertEqual(levels["default"], "internal")
        r = self.client.get(reverse("knowledge-policy-events"), {"document": doc.id})
        self.assertEqual([e["event"] for e in r.data["events"]], ["classified"])
        self.assertEqual(self.client.get(reverse("knowledge-policy-events"), {"document": "x"}).status_code, 400)

    @patch("chat.model_manager.requests.Session.post")
    def test_document_answer_from_confidential_document_carries_the_notice(self, mock_post):
        from documents.services import CONFIDENTIAL_NOTICE as DOC_NOTICE
        doc = self.upload("Secret recipe. CONFIDENTIAL.")
        mock_post.return_value = ok_response("It is a recipe.")
        r = self.client.post(reverse("document-ask", kwargs={"pk": doc.id}), {"question": "What is it?"}, format="json")
        self.assertIn(DOC_NOTICE, r.data["basis"]["warnings"])


class EgressGuardTests(StoreTestMixin, APITestCase):
    """Phase 4: nothing leaves the site unless the database, a fresh scan and a current index allow it."""

    def setUp(self):
        super().setUp()
        self.shared = self.make_doc("sop.txt", "Pump start-up SOP: open suction valve, then start the motor.",
                                    classification="shareable")
        self.mixed = self.make_doc(
            "manual.txt",
            "Pump manual chapter one. " * 60 + "\n\nVendor contact: service@vendor.example\n\n" + "Pump chapter two. " * 60,
            classification="shareable")
        self.secret = self.make_doc("incident.txt", "Pump P-101 incident investigation.", classification="confidential")
        self.site = self.make_doc("shift.txt", "Pump P-101 stopped on night shift.")  # internal (default)
        for d in (self.shared, self.mixed, self.secret, self.site):
            indexing.index_document(d.id)

    def guard(self, candidates=None, **kw):
        return policy.guard_egress(candidates if candidates is not None else store.scroll_sections(),
                                   purpose="test", **kw)

    def test_only_shareable_clean_sections_are_released(self):
        allowed, blocked = self.guard()
        released = {(a["document_name"], a["section"]) for a in allowed}
        self.assertIn(("sop.txt", 0), released)
        self.assertTrue(any(name == "manual.txt" for name, _ in released))   # clean chapters of the manual
        self.assertFalse({"incident.txt", "shift.txt"} & {name for name, _ in released})
        reasons = {b["document_name"]: b["reasons"] for b in blocked}
        self.assertEqual(reasons["incident.txt"], ["Document is confidential"])
        self.assertEqual(reasons["shift.txt"], ["Document is internal"])
        self.assertEqual(reasons["manual.txt"], ["Section contains Email address"])

    def test_released_items_carry_only_whitelisted_fields(self):
        allowed, _ = self.guard()
        self.assertTrue(allowed)
        for item in allowed:
            self.assertEqual(set(item), set(policy.EGRESS_FIELDS))
            self.assertEqual(len(item["content_sha256"]), 64)

    def test_database_wins_over_a_stale_or_forged_payload(self):
        forged = [{**p, "classification": "public"} for p in store.scroll_sections([self.secret.id])]
        allowed, blocked = self.guard(forged)
        self.assertEqual((allowed, blocked[0]["reasons"]), ([], ["Document is confidential"]))
        Document.objects.filter(pk=self.shared.id).update(classification="confidential")
        allowed, _ = self.guard(store.scroll_sections([self.shared.id]))
        self.assertEqual(allowed, [])

    def test_changed_text_unverifiable_and_deleted_documents_are_blocked(self):
        Document.objects.filter(pk=self.shared.id).update(extracted_text="Rewritten SOP.")
        _, blocked = self.guard(store.scroll_sections([self.shared.id]))
        self.assertIn("Index does not match the current document text", blocked[0]["reasons"])
        no_fp = [{"document_id": self.mixed.id, "section": 0, "text": "Pump chapter."}]
        self.assertEqual(self.guard(no_fp)[0], [])
        _, blocked = self.guard([{"document_id": 9999, "text": "x", "fingerprint": "f"}])
        self.assertEqual(blocked[0]["reasons"], ["Document no longer exists"])

    def test_injected_sensitive_text_is_rescanned(self):
        payload = store.scroll_sections([self.shared.id])[0]
        allowed, blocked = self.guard([{**payload, "text": payload["text"] + " password: hunter2"}])
        self.assertEqual(allowed, [])
        self.assertEqual(blocked[0]["reasons"], ["Section contains Password or secret"])

    def test_guard_audits_and_review_does_not(self):
        policy.egress_review()
        self.assertFalse(PolicyEvent.objects.filter(event__startswith="egress").exists())
        self.guard()
        blocked = PolicyEvent.objects.filter(event=PolicyEvent.EGRESS_BLOCKED)
        self.assertEqual({e.document_name for e in blocked}, {"manual.txt", "incident.txt", "shift.txt"})
        self.assertTrue(PolicyEvent.objects.filter(event=PolicyEvent.EGRESS_ALLOWED, document=self.shared).exists())
        self.assertNotIn("vendor.example", json.dumps(list(blocked.values("reason", "detail"))))

    def test_review_api(self):
        r = self.client.get(reverse("knowledge-egress-review"))
        rows = {row["document_name"]: row for row in r.data["documents"]}
        self.assertEqual(rows["sop.txt"]["sections_blocked"], 0)
        self.assertEqual(rows["incident.txt"]["sections_allowed"], 0)
        self.assertFalse(rows["shift.txt"]["may_leave_site"])
        self.assertGreater(rows["manual.txt"]["sections_allowed"], 0)
        self.assertGreater(rows["manual.txt"]["sections_blocked"], 0)
        self.assertEqual(r.data["totals"]["documents_shareable"], 2)

    def test_unindexed_document_in_review(self):
        self.make_doc("new.txt", "Fresh upload.", classification="public")
        rows = {row["document_name"]: row for row in policy.egress_review()["documents"]}
        self.assertEqual(rows["new.txt"]["reasons"], ["Not indexed yet"])
