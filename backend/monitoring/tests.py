import json
import shutil
import tempfile
from datetime import timedelta
from unittest.mock import Mock, patch

import requests
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from chat.tests import ollama_ok, ollama_stream, PNG_B64
from documents.models import Document

from .models import UsageRecord

TEMP_MEDIA = tempfile.mkdtemp(prefix="mrpl-monitoring-test-")
POST = "chat.model_manager.requests.Session.post"
GET = "chat.model_manager.requests.Session.get"


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class UsageRecordingTests(APITestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)

    def chat(self, body):
        return self.client.post(reverse("chat"), body, format="json")

    @patch(POST)
    def test_each_route_recorded_with_model_and_category(self, mock_post):
        mock_post.return_value = ollama_ok("answer")
        self.chat({"message": "Explain federated learning."})
        self.chat({"message": "Write a Python function to calculate factorial."})
        self.chat({"message": "Describe this image.", "images": [PNG_B64]})
        rows = list(UsageRecord.objects.order_by("id").values_list("model", "category", "source", "success"))
        self.assertEqual(rows, [
            ("qwen3:8b", "general", "chat", True),
            ("qwen2.5-coder:7b", "coding", "chat", True),
            ("qwen2.5vl:7b", "vision", "chat", True),
        ])

    @patch(POST)
    def test_no_content_is_stored(self, mock_post):
        mock_post.return_value = ollama_ok("SECRET ANSWER")
        self.chat({"message": "SECRET QUESTION about project X"})
        row = UsageRecord.objects.values().get()
        self.assertNotIn("SECRET", json.dumps(row, default=str))
        self.assertEqual(set(row), {"id", "model", "category", "reason", "source", "success", "error_type",
                                    "duration_ms", "streamed", "regenerated", "stage", "backfilled", "created_at"})

    @patch(POST)
    def test_failures_recorded_without_details(self, mock_post):
        mock_post.side_effect = requests.exceptions.Timeout("secret-host:11434 timed out")
        r = self.chat({"message": "Write a Python function to add numbers."})
        self.assertEqual(r.status_code, 504)
        row = UsageRecord.objects.get()
        self.assertFalse(row.success)
        self.assertEqual((row.model, row.category, row.error_type), ("qwen2.5-coder:7b", "coding", "ModelTimeoutError"))

    @patch(POST)
    def test_needs_image_reply_is_not_counted(self, mock_post):
        self.chat({"message": "Analyze this engineering drawing."})
        self.assertEqual(UsageRecord.objects.count(), 0)

    @patch(POST)
    def test_stream_success_failure_and_disconnect(self, mock_post):
        mock_post.return_value = ollama_stream("ok")
        r = self.client.post(reverse("chat-stream"), {"message": "hi"}, format="json")
        b"".join(r.streaming_content)
        mock_post.return_value = ollama_stream("partial", error="CUDA error: out of memory")
        r = self.client.post(reverse("chat-stream"), {"message": "Describe this image.", "images": [PNG_B64]}, format="json")
        b"".join(r.streaming_content)
        mock_post.return_value = ollama_stream("a", "b", "c")
        r = self.client.post(reverse("chat-stream"), {"message": "hello"}, format="json")
        stream = iter(r.streaming_content)
        next(stream), next(stream)          # read a little, then the client goes away
        r.close()
        rows = list(UsageRecord.objects.order_by("id").values_list("success", "error_type", "streamed"))
        self.assertEqual(rows, [(True, "", True), (False, "ModelResourceError", True), (False, "ClientDisconnected", True)])

    @patch(POST)
    def test_document_question_and_summary_recorded(self, mock_post):
        mock_post.return_value = ollama_ok("ok")
        doc = Document.objects.create(original_name="d.txt", file_type="TXT", extracted_text="Temp: 120 C")
        self.client.post(reverse("document-ask", kwargs={"pk": doc.id}), {"question": "Temp?"}, format="json")
        self.client.post(reverse("document-summary", kwargs={"pk": doc.id}), {}, format="json")
        self.assertEqual(list(UsageRecord.objects.order_by("id").values_list("source", "category")),
                         [("document", "general"), ("summary", "general")])


class UsageDashboardTests(APITestCase):
    def make(self, model, category, success=True, days_ago=0):
        r = UsageRecord.objects.create(model=model, category=category, success=success)
        if days_ago:
            UsageRecord.objects.filter(pk=r.pk).update(created_at=timezone.now() - timedelta(days=days_ago))

    def test_empty(self):
        d = self.client.get(reverse("dashboard-usage")).data
        self.assertEqual((d["total_queries"], d["successful_queries"], d["failed_queries"], d["today"]), (0, 0, 0, 0))
        self.assertEqual(d["models"], {"qwen3:8b": 0, "qwen2.5-coder:7b": 0, "qwen2.5vl:7b": 0})
        self.assertEqual(d["routing"], {"general": 0, "coding": 0, "vision": 0})

    def test_aggregation(self):
        self.make("qwen3:8b", "general")
        self.make("qwen3:8b", "general", success=False)
        self.make("qwen2.5-coder:7b", "coding", days_ago=3)
        self.make("qwen2.5vl:7b", "vision")
        d = self.client.get(reverse("dashboard-usage"), {"tz_offset": -330}).data
        self.assertEqual((d["total_queries"], d["successful_queries"], d["failed_queries"]), (4, 3, 1))
        self.assertEqual(d["today"], 3)
        self.assertEqual(d["models"], {"qwen3:8b": 2, "qwen2.5-coder:7b": 1, "qwen2.5vl:7b": 1})
        self.assertEqual(d["routing"], {"general": 2, "coding": 1, "vision": 1})
        self.assertEqual(sum(d["routing"].values()), d["total_queries"])
        qwen3 = next(m for m in d["model_details"] if m["model"] == "qwen3:8b")
        self.assertEqual((qwen3["successful"], qwen3["failed"]), (1, 1))
        self.assertIsNotNone(qwen3["last_success"])


def _resp(payload):
    r = Mock(status_code=200)
    r.json.return_value = payload
    r.raise_for_status = Mock()
    return r


def fake_ollama(installed=("qwen3:8b", "qwen2.5-coder:7b", "qwen2.5vl:7b"), loaded=("qwen3:8b",)):
    def get(url, **kwargs):
        if url.endswith("/api/version"):
            return _resp({"version": "0.33.3"})
        if url.endswith("/api/tags"):
            return _resp({"models": [{"name": n, "size": 5_000_000_000} for n in installed]})
        if url.endswith("/api/ps"):
            return _resp({"models": [{"name": n, "size_vram": 5_500_000_000, "context_length": 8192} for n in loaded]})
        raise AssertionError(url)
    return get


class SystemStatusTests(APITestCase):
    @patch(POST)
    @patch(GET, side_effect=fake_ollama())
    def test_all_ready_without_inference(self, mock_get, mock_post):
        d = self.client.get(reverse("dashboard-status")).data
        self.assertEqual(d["services"]["backend"]["state"], "ready")
        self.assertEqual(d["services"]["ollama"]["label"], "Connected")
        self.assertEqual([m["state"] for m in d["models"]], ["ready"] * 3)
        self.assertEqual([m["capability_label"] for m in d["models"]],
                         ["General Reasoning", "Code Generation", "Vision / Multimodal"])
        self.assertTrue(d["models"][0]["loaded"])
        self.assertFalse(d["models"][1]["loaded"])
        mock_post.assert_not_called()  # no generation / model loading
        called = sorted(c.args[0].rsplit("/", 1)[-1] for c in mock_get.call_args_list)
        self.assertEqual(called, ["ps", "tags", "version"])
        self.assertTrue(all(c.kwargs["timeout"] <= 3 for c in mock_get.call_args_list))

    @patch(GET, side_effect=fake_ollama(installed=("qwen3:8b", "qwen2.5-coder:7b")))
    def test_missing_model_is_unavailable(self, mock_get):
        d = self.client.get(reverse("dashboard-status")).data
        vl = next(m for m in d["models"] if m["id"] == "qwen-vl")
        self.assertEqual((vl["state"], vl["label"]), ("unavailable", "Unavailable"))
        self.assertEqual(vl["reason"], "Model is not available through the local Ollama service.")

    @patch(GET, side_effect=requests.exceptions.ConnectionError("Connection refused to 127.0.0.1:11434"))
    def test_ollama_down_does_not_crash_or_leak(self, mock_get):
        r = self.client.get(reverse("dashboard-status"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["services"]["ollama"]["state"], "unavailable")
        self.assertEqual([m["state"] for m in r.data["models"]], ["unavailable"] * 3)
        self.assertNotIn("Connection refused", json.dumps(r.data, default=str))
        self.assertNotIn("11434", json.dumps(r.data, default=str))

    @override_settings(OLLAMA_URL="http://8.8.8.8:11434")
    def test_public_ollama_url_reported_as_misconfigured(self):
        d = self.client.get(reverse("dashboard-status")).data
        self.assertEqual(d["services"]["ollama"]["label"], "Misconfigured")

    @patch(GET, side_effect=fake_ollama())
    def test_ocr_not_installed(self, mock_get):
        with patch("monitoring.health.importlib.util.find_spec", return_value=None):
            d = self.client.get(reverse("dashboard-status")).data
        self.assertEqual(d["services"]["ocr"]["label"], "Not installed")

    @patch(GET, side_effect=fake_ollama())
    def test_ocr_models_missing(self, mock_get):
        empty = tempfile.mkdtemp()
        with patch("monitoring.health._paddlex_models_dir", return_value=__import__("pathlib").Path(empty)):
            d = self.client.get(reverse("dashboard-status")).data
        shutil.rmtree(empty, ignore_errors=True)
        self.assertEqual(d["services"]["ocr"]["state"], "unavailable")
        self.assertIn("not found", d["services"]["ocr"]["reason"])


_sync_override = override_settings(DOCUMENT_ASYNC_PROCESSING=False)


def setUpModule():
    from chat.tests import start_loaded_patchers
    start_loaded_patchers()
    _sync_override.enable()


def tearDownModule():
    from chat.tests import stop_loaded_patchers
    stop_loaded_patchers()
    _sync_override.disable()


class GpuStatusTests(APITestCase):
    CSV = ("NVIDIA GeForce RTX 5050 Laptop GPU, 595.84, 6075, 8151, {util}, 53, 9.2, {limit}, 55.00, 180, 3090, "
           "{cap}, Not Active, Not Active, P8")

    def run_with(self, util=99, limit="10.00", cap="Active", source="battery"):
        from . import health
        proc = Mock(stdout=self.CSV.format(util=util, limit=limit, cap=cap))
        with patch("shutil.which", return_value="/usr/bin/nvidia-smi"), \
                patch("subprocess.run", return_value=proc), \
                patch.object(health, "_power_source", return_value=source):
            return health.gpu_status()

    def test_battery_power_cap_is_reported(self):
        g = self.run_with()
        self.assertEqual((g["state"], g["label"]), ("degraded", "Limited"))
        self.assertTrue(any("battery" in w for w in g["warnings"]))
        self.assertTrue(any("10 W" in w for w in g["warnings"]))

    def test_healthy_on_ac(self):
        g = self.run_with(util=0, limit="55.00", cap="Not Active", source="ac")
        self.assertEqual(g["state"], "ready")
        self.assertEqual(g["memory_total_mb"], 8151)

    def test_no_nvidia_smi(self):
        from . import health
        with patch("shutil.which", return_value=None):
            self.assertEqual(health.gpu_status()["state"], "unavailable")


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class FeedbackTrendBackfillTests(APITestCase):
    def setUp(self):
        from chat.tests import start_loaded_patchers
        start_loaded_patchers()

    def chat(self, body):
        return self.client.post(reverse("chat"), body, format="json")

    @patch(POST, return_value=ollama_ok("answer"))
    def test_feedback_roundtrip_and_helpfulness(self, _):
        from chat.models import ChatMessage
        r = self.chat({"message": "Explain federated learning."})
        answer_id = r.data["assistant_message_id"]
        url = reverse("message-feedback", kwargs={"pk": answer_id})
        self.assertEqual(self.client.post(url, {"value": "up"}, format="json").status_code, 200)
        self.assertEqual(ChatMessage.objects.get(pk=answer_id).feedback, "up")
        conv = self.client.get(reverse("conversation-detail", kwargs={"pk": r.data["conversation_id"]}))
        self.assertEqual(conv.data["conversation"]["messages"][1]["feedback"], "up")
        usage = self.client.get(reverse("dashboard-usage")).data
        qwen3 = next(m for m in usage["model_details"] if m["model"] == "qwen3:8b")
        self.assertEqual(qwen3["feedback"], {"up": 1, "down": 0})
        self.assertEqual(usage["feedback"], {"up": 1, "down": 0})
        # clear, invalid value, user message, unknown id
        self.client.post(url, {"value": None}, format="json")
        self.assertEqual(ChatMessage.objects.get(pk=answer_id).feedback, "")
        self.assertEqual(self.client.post(url, {"value": "meh"}, format="json").status_code, 400)
        user_id = r.data["user_message_id"]
        self.assertEqual(self.client.post(reverse("message-feedback", kwargs={"pk": user_id}),
                                          {"value": "up"}, format="json").status_code, 404)

    @patch(POST, return_value=ollama_ok("answer"))
    def test_regenerate_is_flagged(self, _):
        r = self.chat({"message": "Explain federated learning."})
        self.chat({"conversation_id": r.data["conversation_id"], "regenerate": True})
        self.assertEqual(list(UsageRecord.objects.order_by("id").values_list("regenerated", flat=True)), [False, True])
        self.assertEqual(self.client.get(reverse("dashboard-usage")).data["regenerated"], 1)

    def test_trend_has_fourteen_zero_filled_days(self):
        UsageRecord.objects.create(model="qwen3:8b", category="general", success=True, duration_ms=1000)
        UsageRecord.objects.create(model="qwen3:8b", category="general", success=False)
        old = UsageRecord.objects.create(model="qwen3:8b", category="general", success=True, duration_ms=3000)
        UsageRecord.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=3))
        UsageRecord.objects.create(model="paddleocr", category="vision", success=False, stage="ocr")
        trend = self.client.get(reverse("dashboard-usage")).data["trend"]
        self.assertEqual(len(trend), 14)
        self.assertEqual(trend[-1], {"date": trend[-1]["date"], "total": 2, "failed": 1, "avg_ms": 1000})
        self.assertEqual(trend[-4]["total"], 1)
        self.assertEqual(sum(d["total"] for d in trend), 3)  # the OCR failure is not a model call

    @patch("documents.processing.ocr_images", side_effect=__import__("documents.ocr", fromlist=["OCRError"]).OCRError("x"))
    def test_ocr_failure_before_model_is_recorded(self, _):
        r = self.chat({"message": "Read the text in this scanned document.", "images": [PNG_B64]})
        self.assertEqual(r.status_code, 503)
        row = UsageRecord.objects.get()
        self.assertEqual((row.stage, row.success, row.model), ("ocr", False, "paddleocr"))
        usage = self.client.get(reverse("dashboard-usage")).data
        self.assertEqual(usage["total_queries"], 0)
        self.assertEqual(usage["pre_model_failures"], {"ocr": 1})

    def test_backfill_dry_run_then_apply_is_idempotent(self):
        from io import StringIO
        from django.core.management import call_command
        from chat.models import Conversation, ChatMessage
        conv = Conversation.objects.create(title="old")
        ChatMessage.objects.create(conversation=conv, role="user", content="q")
        ChatMessage.objects.create(conversation=conv, role="assistant", content="def f(): pass",
                                   model="qwen2.5-coder:7b", routing_reason="coding")
        out = StringIO()
        call_command("backfill_usage", stdout=out)
        self.assertIn("Dry run", out.getvalue())
        self.assertEqual(UsageRecord.objects.count(), 0)
        call_command("backfill_usage", "--apply", stdout=StringIO())
        row = UsageRecord.objects.get()
        self.assertEqual((row.model, row.category, row.backfilled), ("qwen2.5-coder:7b", "coding", True))
        self.assertEqual(ChatMessage.objects.get(role="assistant").basis, "code")
        call_command("backfill_usage", "--apply", stdout=StringIO())
        self.assertEqual(UsageRecord.objects.count(), 1)

    def test_prune_respects_dry_run_and_retention(self):
        from io import StringIO
        from django.core.management import call_command
        old = UsageRecord.objects.create(model="qwen3:8b", category="general", success=True)
        UsageRecord.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=400))
        UsageRecord.objects.create(model="qwen3:8b", category="general", success=True)
        call_command("prune_usage", stdout=StringIO())
        self.assertEqual(UsageRecord.objects.count(), 2)
        call_command("prune_usage", "--apply", stdout=StringIO())
        self.assertEqual(UsageRecord.objects.count(), 1)


class DatabaseDiskDeepCheckTests(APITestCase):
    def test_database_and_disk_reported(self):
        from . import health
        db = health.database_status()
        self.assertEqual(db["state"], "ready")
        disk = health.disk_status()
        self.assertIn(disk["state"], ("ready", "degraded"))
        self.assertGreater(disk["total_bytes"], 0)

    def test_low_disk_warns(self):
        from collections import namedtuple
        from . import health
        du = namedtuple("du", "total used free")
        with patch("monitoring.health.shutil.disk_usage", return_value=du(100 * 1024 ** 3, 99 * 1024 ** 3, 1024 ** 3)):
            disk = health.disk_status()
        self.assertEqual(disk["state"], "degraded")
        self.assertIn("Low disk space", disk["warnings"][0])

    def test_deep_check_validates_target(self):
        url = reverse("dashboard-deep-check")
        self.assertEqual(self.client.post(url, {}, format="json").status_code, 400)
        self.assertEqual(self.client.post(url, {"target": "gpt-4"}, format="json").status_code, 400)

    @patch(POST, return_value=ollama_ok("OK"))
    def test_model_deep_check_is_not_counted_as_usage(self, mock_post):
        r = self.client.post(reverse("dashboard-deep-check"), {"target": "qwen3"}, format="json")
        self.assertTrue(r.data["success"])
        self.assertEqual(UsageRecord.objects.count(), 0)

    @patch(POST, side_effect=requests.exceptions.ConnectionError("secret-host refused"))
    def test_model_deep_check_failure_is_user_safe(self, _):
        r = self.client.post(reverse("dashboard-deep-check"), {"target": "qwen3"}, format="json")
        self.assertFalse(r.data["success"])
        self.assertNotIn("secret-host", r.data["detail"])

    @patch("documents.ocr.ocr_image", return_value={"text": "PUMP P-101 PRESSURE 12.5 BAR", "confidence": 0.99})
    def test_ocr_deep_check(self, _):
        r = self.client.post(reverse("dashboard-deep-check"), {"target": "ocr"}, format="json")
        self.assertTrue(r.data["success"], r.data)
