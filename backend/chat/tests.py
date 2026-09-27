import base64
import io
from unittest.mock import patch, Mock

import requests
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .services import ask_ollama
from .model_registry import MODEL_REGISTRY, get_model, UnknownModelError
from .model_manager import ModelManager, ModelRequestError
from .router import route_model

import io as _io
from PIL import Image as _Image


def make_image_b64(width=64, height=32, fmt="PNG"):
    buf = _io.BytesIO()
    _Image.new("RGB", (width, height), (200, 30, 30)).save(buf, fmt)
    return base64.b64encode(buf.getvalue()).decode()


PNG_B64 = make_image_b64()

# Keep test uploads (chat attachments) out of the real media folder.
import shutil as _shutil
import tempfile as _tempfile
_media_override = None


def setUpModule():
    global _media_override
    _media_override = override_settings(MEDIA_ROOT=_tempfile.mkdtemp(prefix="mrpl-chat-test-"))
    _media_override.enable()


def tearDownModule():
    from django.conf import settings as _settings
    root = _settings.MEDIA_ROOT
    _media_override.disable()
    _shutil.rmtree(root, ignore_errors=True)


def sent_user_message(mock_post):
    """Last user message of the /api/chat payload sent to Ollama."""
    return mock_post.call_args.kwargs["json"]["messages"][-1]


def ollama_ok(text="ok"):
    mock_response = Mock()
    mock_response.status_code = 200
    # Works for both /api/generate ("response") and /api/chat ("message").
    mock_response.json.return_value = {
        "response": text, "message": {"role": "assistant", "content": text},
        "done": True, "eval_count": 3,
    }
    mock_response.raise_for_status = Mock()
    return mock_response


class ChatAPITests(APITestCase):
    def setUp(self):
        self.chat_url = reverse("chat")

    @patch("chat.model_manager.requests.Session.post")
    def test_valid_message_success(self, mock_post):
        """Backward compatibility: no model given -> default model is used."""
        mock_post.return_value = ollama_ok("Hello! I am your local AI assistant running on PC5.")

        response = self.client.post(self.chat_url, {"message": "Hello AI"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data.get("success"))
        self.assertEqual(
            response.data.get("response"),
            "Hello! I am your local AI assistant running on PC5."
        )
        self.assertEqual(response.data.get("model"), "qwen3")
        self.assertEqual(response.data.get("ollama_model"), "qwen3:8b")
        self.assertFalse(response.data.get("external_api"))

        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertTrue(args[0].endswith("/api/chat"))
        self.assertEqual(kwargs["json"]["messages"], [{"role": "user", "content": "Hello AI"}])
        self.assertEqual(kwargs["json"]["model"], "qwen3:8b")
        self.assertFalse(kwargs["json"]["stream"])
        self.assertNotIn("images", kwargs["json"])

    @patch("chat.model_manager.requests.Session.post")
    def test_each_registered_model_routes_to_its_ollama_tag(self, mock_post):
        mock_post.return_value = ollama_ok()
        for model_id, model in MODEL_REGISTRY.items():
            with self.subTest(model=model_id):
                response = self.client.post(
                    self.chat_url, {"message": "hi", "model": model_id}, format="json"
                )
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertEqual(response.data["model"], model_id)
                self.assertEqual(mock_post.call_args.kwargs["json"]["model"], model.ollama_name)

    @patch("chat.model_manager.requests.Session.post")
    def test_omitted_model_uses_auto_routing(self, mock_post):
        mock_post.return_value = ollama_ok()
        response = self.client.post(
            self.chat_url, {"message": "Write a Python function to add two numbers."}, format="json"
        )
        self.assertEqual(response.data["model"], "qwen-coder")
        self.assertEqual(response.data["ollama_model"], "qwen2.5-coder:7b")
        self.assertEqual({k: v for k, v in response.data["routing"].items() if k != "explanation"}, {"mode": "auto", "reason": "coding"})
        self.assertEqual(mock_post.call_args.kwargs["json"]["model"], "qwen2.5-coder:7b")

    @patch("chat.model_manager.requests.Session.post")
    def test_manual_model_overrides_router(self, mock_post):
        mock_post.return_value = ollama_ok()
        response = self.client.post(
            self.chat_url,
            {"message": "Write a Python function to add two numbers.", "model": "qwen3"},
            format="json",
        )
        self.assertEqual(response.data["model"], "qwen3")
        self.assertEqual({k: v for k, v in response.data["routing"].items() if k != "explanation"}, {"mode": "manual", "reason": "manual"})

    @patch("chat.model_manager.requests.Session.post")
    def test_auto_with_image_routes_to_vision(self, mock_post):
        mock_post.return_value = ollama_ok()
        response = self.client.post(
            self.chat_url,
            {"message": "What is this?", "model": "auto", "images": [PNG_B64]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["model"], "qwen-vl")
        self.assertEqual(response.data["routing"]["reason"], "vision")
        self.assertEqual(sent_user_message(mock_post)["images"], [PNG_B64])

    @patch("chat.model_manager.requests.Session.post")
    def test_routing_returned_on_error(self, mock_post):
        mock_post.side_effect = requests.exceptions.ConnectionError()
        response = self.client.post(
            self.chat_url, {"message": "Analyze this P&ID.", "images": [PNG_B64]}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.data["model"], "qwen-vl")
        self.assertEqual(response.data["routing"]["reason"], "vision")

    @patch("chat.model_manager.requests.Session.post")
    def test_invalid_model_name(self, mock_post):
        response = self.client.post(
            self.chat_url, {"message": "hi", "model": "gpt-4"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("model", response.data)
        mock_post.assert_not_called()

    def test_empty_message(self):
        """Test that an empty message string returns 400 Bad Request."""
        response = self.client.post(self.chat_url, {"message": ""}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("message", response.data)

    def test_missing_message_field(self):
        """Test that omitting the message field returns 400 Bad Request."""
        response = self.client.post(self.chat_url, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("message", response.data)

    @patch("chat.model_manager.requests.Session.post")
    def test_ollama_server_connection_error(self, mock_post):
        """Test that connection failure to Ollama returns HTTP 503."""
        mock_post.side_effect = requests.exceptions.ConnectionError("Connection refused")

        response = self.client.post(self.chat_url, {"message": "Test server down"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertFalse(response.data.get("success"))
        self.assertEqual(response.data.get("error"), "Local AI server is unavailable.")
        self.assertNotIn("Connection refused", str(response.data))

    @patch("chat.model_manager.requests.Session.post")
    def test_ollama_server_timeout(self, mock_post):
        """Test that timeout when contacting Ollama returns HTTP 504."""
        mock_post.side_effect = requests.exceptions.Timeout("Request timed out")

        response = self.client.post(self.chat_url, {"message": "Test timeout"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_504_GATEWAY_TIMEOUT)
        self.assertFalse(response.data.get("success"))
        self.assertIn("timed out", response.data.get("error"))

    @patch("chat.model_manager.requests.Session.post")
    def test_ollama_server_http_error(self, mock_post):
        """Test that HTTP error (e.g. 500) from Ollama returns a clean 502."""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "internal error"
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("500 Server Error")
        mock_post.return_value = mock_response

        response = self.client.post(self.chat_url, {"message": "Test HTTP error"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertFalse(response.data.get("success"))
        self.assertEqual(
            response.data.get("error"), "The local AI model failed to process the request."
        )
        self.assertNotIn("500 Server Error", str(response.data))

    @patch("chat.model_manager.requests.Session.post")
    def test_model_not_installed_in_ollama(self, mock_post):
        mock_response = Mock()
        mock_response.status_code = 404
        mock_post.return_value = mock_response

        response = self.client.post(
            self.chat_url, {"message": "hi", "model": "qwen-coder"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertIn("not installed", response.data["error"])

    @patch("chat.model_manager.requests.Session.post")
    def test_image_sent_to_vision_model(self, mock_post):
        mock_post.return_value = ollama_ok("A diagram.")
        response = self.client.post(
            self.chat_url,
            {"message": "Describe", "model": "qwen-vl", "images": [f"data:image/png;base64,{PNG_B64}"]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "qwen2.5vl:7b")
        self.assertEqual(payload["messages"][-1]["images"], [PNG_B64])  # data: prefix stripped

    @patch("chat.model_manager.requests.Session.post")
    def test_image_rejected_for_text_model(self, mock_post):
        response = self.client.post(
            self.chat_url,
            {"message": "Describe", "model": "qwen3", "images": [PNG_B64]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("images", response.data)
        mock_post.assert_not_called()

    def test_invalid_image_data_rejected(self):
        for bad in ("not-base64!!", base64.b64encode(b"GIF89a....").decode()):
            with self.subTest(bad=bad):
                response = self.client.post(
                    self.chat_url,
                    {"message": "Describe", "model": "qwen-vl", "images": [bad]},
                    format="json",
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("chat.model_manager.requests.Session.post")
    def test_ask_ollama_service_direct(self, mock_post):
        """Direct unit test for the backward-compatible ask_ollama helper."""
        mock_post.return_value = ollama_ok("Direct service output")
        result = ask_ollama("Direct query")
        self.assertEqual(result, "Direct service output")


class ModelListAPITests(APITestCase):
    def test_lists_registered_models(self):
        response = self.client.get(reverse("models"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [m["id"] for m in response.data["models"]]
        self.assertEqual(ids, ["qwen3", "qwen-coder", "qwen-vl"])
        self.assertEqual(response.data["default"], "qwen3")
        vl = response.data["models"][2]
        self.assertEqual(vl["capability"], "vision")
        self.assertEqual(vl["modality"], "multimodal")
        self.assertTrue(vl["supports_images"])


class ModelManagerTests(APITestCase):
    def test_unknown_model_raises(self):
        with self.assertRaises(UnknownModelError):
            get_model("does-not-exist")

    @patch("chat.model_manager.requests.Session.post")
    def test_images_refused_for_text_model(self, mock_post):
        with self.assertRaises(ModelRequestError):
            ModelManager().generate("qwen-coder", "hi", images=[PNG_B64])
        mock_post.assert_not_called()

    @override_settings(OLLAMA_URL="http://127.0.0.1:11434", OLLAMA_TIMEOUT=42)
    @patch("chat.model_manager.requests.Session.post")
    def test_uses_local_ollama_and_timeout(self, mock_post):
        mock_post.return_value = ollama_ok()
        ModelManager().generate("qwen3", "hi")
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "http://127.0.0.1:11434/api/generate")
        self.assertEqual(kwargs["timeout"], 42)


class RouterTests(APITestCase):
    """Step 8 routing cases (deterministic, no inference)."""

    CASES = [
        # (message, expected ollama model, expected reason)
        ("Explain what federated learning is and why it is useful.", "qwen3:8b", "general_reasoning"),
        ("Write a Python program to calculate the average of numbers.", "qwen2.5-coder:7b", "coding"),
        ("Analyze this P&ID and identify the major components.", "qwen2.5vl:7b", "vision"),
        ("Summarize this industrial inspection report.", "qwen3:8b", "general_reasoning"),
        ("Write a Python function to calculate factorial.", "qwen2.5-coder:7b", "coding"),
        ("Explain federated learning.", "qwen3:8b", "general_reasoning"),
        ("Analyze this scanned inspection report.", "qwen2.5vl:7b", "vision"),
        ("How do I fix this C++ compile error?", "qwen2.5-coder:7b", "coding"),
        ("Write a SQL query for the Django app.", "qwen2.5-coder:7b", "coding"),
        ("Read this handwritten document.", "qwen2.5vl:7b", "vision"),
        ("Perform a visual inspection of the weld photograph.", "qwen2.5vl:7b", "vision"),
        ("Run OCR on the attached page.", "qwen2.5vl:7b", "vision"),
    ]

    def test_required_cases(self):
        for message, model, reason in self.CASES:
            with self.subTest(message=message):
                decision = route_model(message)
                self.assertEqual(decision["model"], model)
                self.assertEqual(decision["reason"], reason)

    def test_whole_word_matching(self):
        # "class" inside "classify", "code" inside "barcode", "react" inside "reactor"
        for message in ("Classify these risks.", "What is a barcode?", "Explain reactor cooling."):
            with self.subTest(message=message):
                self.assertEqual(route_model(message)["reason"], "general_reasoning")

    def test_case_insensitive(self):
        self.assertEqual(route_model("PYTHON please")["reason"], "coding")
        self.assertEqual(route_model("check the p&id")["reason"], "vision")

    def test_tie_goes_to_coding_and_majority_wins(self):
        self.assertEqual(route_model("Write a function to resize an image.")["reason"], "coding")
        self.assertEqual(
            route_model("Describe the diagram in this scanned image of the code.")["reason"], "vision"
        )

    def test_attached_image_forces_vision(self):
        decision = route_model("Write Python code for this.", has_images=True)
        self.assertEqual(decision["reason"], "vision")
        self.assertEqual(decision["model_id"], "qwen-vl")

    def test_empty_message_is_general(self):
        self.assertEqual(route_model("")["reason"], "general_reasoning")

    def test_route_endpoint(self):
        url = reverse("chat-route")
        response = self.client.post(
            url, {"message": "Analyze this P&ID and identify the major components."}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["model"], "qwen2.5vl:7b")
        self.assertEqual(response.data["reason"], "vision")
        self.assertTrue(any("p&id" in m for m in response.data["matched"]))
        self.assertTrue(response.data["requires_image"])
        self.assertEqual(self.client.post(url, {}, format="json").status_code, 400)


class ExecutionLayerTests(APITestCase):
    """Step 8: router decides WHICH model, execution layer decides HOW to call it."""

    CASES = [
        ("Explain federated learning.", "qwen3:8b", "general_reasoning"),
        ("Write a Python function to reverse a linked list.", "qwen2.5-coder:7b", "coding"),
        ("Analyze this engineering drawing.", "qwen2.5vl:7b", "vision"),
    ]

    @patch("chat.model_manager.requests.Session.post")
    def test_router_output_feeds_execution_layer(self, mock_post):
        from .model_manager import generate_response
        mock_post.return_value = ollama_ok("done")
        for message, tag, reason in self.CASES:
            with self.subTest(message=message):
                decision = route_model(message)
                self.assertEqual((decision["model"], decision["reason"]), (tag, reason))
                result = generate_response(decision["model"], message)
                self.assertEqual(result["ollama_model"], tag)
                self.assertEqual(mock_post.call_args.kwargs["json"]["model"], tag)

    @patch("chat.model_manager.requests.Session.post")
    def test_chat_api_uses_router_then_execution(self, mock_post):
        mock_post.return_value = ollama_ok("done")
        for message, tag, reason in self.CASES:
            with self.subTest(message=message):
                body = {"message": message}
                if reason == "vision":
                    body["images"] = [PNG_B64]
                response = self.client.post(reverse("chat"), body, format="json")
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertEqual(response.data["ollama_model"], tag)
                self.assertEqual({k: v for k, v in response.data["routing"].items() if k != "explanation"}, {"mode": "auto", "reason": reason})

    def test_router_contains_no_ollama_http_logic(self):
        import inspect
        from . import router
        source = inspect.getsource(router)
        self.assertNotIn("import requests", source)
        self.assertNotIn("OLLAMA_URL", source)
        self.assertNotIn("/api/generate", source)

    @override_settings(OLLAMA_URL="http://8.8.8.8:11434")
    @patch("chat.model_manager.requests.Session.post")
    def test_public_ollama_url_is_refused(self, mock_post):
        from .model_manager import generate_response, NonLocalEndpointError
        with self.assertRaises(NonLocalEndpointError):
            generate_response("qwen3:8b", "hi")
        response = self.client.post(reverse("chat"), {"message": "hi"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.data["error"], "Local AI server is misconfigured.")
        mock_post.assert_not_called()

    @override_settings(OLLAMA_ALLOWED_HOSTS=["192.168.1.50", "10.20.0.0/16"])
    @patch("chat.model_manager.requests.Session.post")
    def test_localhost_and_allowlisted_lan_urls_allowed(self, mock_post):
        from .model_manager import ModelManager
        mock_post.return_value = ollama_ok()
        for url in ("http://localhost:11434", "http://127.0.0.1:11434",
                    "http://192.168.1.50:11434", "http://10.20.3.4:11434"):
            with self.subTest(url=url):
                ModelManager(base_url=url).generate("qwen3", "hi")
                self.assertTrue(mock_post.call_args.args[0].startswith(url))
                self.assertFalse(mock_post.call_args.kwargs["allow_redirects"])

    @override_settings(OLLAMA_ALLOWED_HOSTS=["192.168.1.50", "8.8.8.8"])
    @patch("chat.model_manager.requests.Session.post")
    def test_unlisted_lan_public_and_link_local_refused(self, mock_post):
        from .model_manager import ModelManager, NonLocalEndpointError
        for url in ("http://192.168.1.99:11434",          # private but not allow-listed
                    "http://8.8.8.8:11434",               # public, even though listed
                    "http://169.254.169.254:11434",       # link-local / cloud metadata
                    "http://0.0.0.0:11434"):
            with self.subTest(url=url):
                with self.assertRaises(NonLocalEndpointError):
                    ModelManager(base_url=url).generate("qwen3", "hi")
        mock_post.assert_not_called()

    @patch("chat.model_manager.requests.Session.post")
    def test_redirect_from_ollama_is_refused(self, mock_post):
        from .model_manager import generate_response, NonLocalEndpointError
        redirect = Mock(status_code=302, text="")
        mock_post.return_value = redirect
        with self.assertRaises(NonLocalEndpointError):
            generate_response("qwen3", "hi")

    def test_proxy_environment_is_ignored(self):
        from .model_manager import _session
        self.assertFalse(_session().trust_env)

    @patch("chat.model_manager.requests.Session.post")
    def test_gpu_oom_returns_clean_error(self, mock_post):
        mock_post.return_value = Mock(status_code=500, text='{"error":"CUDA error: out of memory"}')
        response = self.client.post(
            reverse("chat"), {"message": "Describe this image.", "images": [PNG_B64]}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertIn("ran out of memory", response.data["error"])
        self.assertNotIn("CUDA", response.data["error"])

    @patch("chat.model_manager.requests.Session.post")
    def test_num_ctx_and_think_options(self, mock_post):
        from .model_manager import generate_response
        mock_post.return_value = ollama_ok()
        generate_response("qwen3", "hi")
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["options"]["num_ctx"], 8192)
        self.assertNotIn("think", payload)  # default: model decides
        with override_settings(OLLAMA_THINK=False):
            generate_response("qwen3", "hi")
            self.assertIs(mock_post.call_args.kwargs["json"]["think"], False)
            generate_response("qwen-coder", "hi")  # not a thinking model
            self.assertNotIn("think", mock_post.call_args.kwargs["json"])
        with override_settings(OLLAMA_NUM_CTX=4096):
            generate_response("qwen3", "hi")
            self.assertEqual(mock_post.call_args.kwargs["json"]["options"]["num_ctx"], 4096)

    def test_unknown_model_tag_rejected(self):
        from .model_manager import generate_response
        with self.assertRaises(UnknownModelError):
            generate_response("gpt-4o", "hi")


class ImageSafetyTests(APITestCase):
    """Phase A: backend-enforced image limits (L1, L2) and vision-without-image (L9)."""

    @patch("chat.model_manager.requests.Session.post")
    def test_large_image_is_downscaled_before_inference(self, mock_post):
        mock_post.return_value = ollama_ok("big")
        response = self.client.post(
            reverse("chat"),
            {"message": "Describe this image.", "images": [make_image_b64(3840, 2160, "JPEG")]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sent = _Image.open(_io.BytesIO(base64.b64decode(sent_user_message(mock_post)["images"][0])))
        self.assertEqual(sent.size, (1024, 576))  # aspect ratio preserved
        self.assertEqual(sent.format, "JPEG")
        info = response.data["images"][0]
        self.assertTrue(info["resized"])
        self.assertEqual((info["original_width"], info["original_height"]), (3840, 2160))

    @patch("chat.model_manager.requests.Session.post")
    def test_small_image_passed_through_unchanged(self, mock_post):
        mock_post.return_value = ollama_ok()
        original = make_image_b64(800, 600)
        self.client.post(reverse("chat"), {"message": "Describe this image.", "images": [original]}, format="json")
        self.assertEqual(sent_user_message(mock_post)["images"], [original])

    @override_settings(VISION_MAX_INPUT_PIXELS=1_000_000)
    def test_oversized_image_rejected_cleanly(self):
        response = self.client.post(
            reverse("chat"),
            {"message": "Describe this image.", "images": [make_image_b64(2000, 1000)]}, format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("too large", str(response.data["images"]))

    @patch("chat.model_manager.requests.Session.post")
    def test_multiple_images_up_to_limit(self, mock_post):
        mock_post.return_value = ollama_ok()
        response = self.client.post(
            reverse("chat"),
            {"message": "Compare these images.", "images": [PNG_B64] * 3}, format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(sent_user_message(mock_post)["images"]), 3)
        too_many = self.client.post(
            reverse("chat"),
            {"message": "Compare these images.", "images": [PNG_B64] * 4}, format="json",
        )
        self.assertEqual(too_many.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("chat.model_manager.requests.Session.post")
    def test_vision_request_without_image_asks_for_one(self, mock_post):
        response = self.client.post(
            reverse("chat"), {"message": "Analyze this engineering drawing."}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["needs_image"])
        self.assertIsNone(response.data["model"])
        self.assertIn("attach", response.data["response"])
        mock_post.assert_not_called()

    @patch("chat.model_manager.requests.Session.post")
    def test_manual_vl_without_image_still_runs(self, mock_post):
        mock_post.return_value = ollama_ok("text answer")
        response = self.client.post(
            reverse("chat"), {"message": "Analyze this drawing.", "model": "qwen-vl"}, format="json"
        )
        self.assertEqual(response.data["model"], "qwen-vl")
        mock_post.assert_called_once()


class RoutingRulesTests(APITestCase):
    """Phase B: phrase/negative rules, visual targets, mixed requests, context (L7-L11, L24)."""

    # (message, context, has_images, expected reason, expected requires_image)
    CASES = [
        ("Explain what federated learning is and why it is useful.", {}, False, "general_reasoning", False),
        ("Explain what a P&ID is in 3 points.", {}, False, "general_reasoning", False),
        ("Write a Python function to calculate the average of a list.", {}, False, "coding", False),
        ("Analyze this engineering drawing.", {}, False, "vision", True),
        ("Analyze this engineering drawing.", {}, True, "vision", False),
        ("Summarize this industrial inspection report.", {}, False, "general_reasoning", False),
        ("fix my script", {}, False, "coding", False),
        ("It crashes, can you fix my script?", {}, False, "coding", False),
        ("How can we reduce human error during inspections?", {}, False, "general_reasoning", False),
        ("Design a training program for new operators.", {}, False, "general_reasoning", False),
        ("Be careful about drawing conclusions from a single reading.", {}, False, "general_reasoning", False),
        ("What colour is the pipe?", {}, False, "general_reasoning", False),
        ("What colour is the pipe?", {"image_available": True}, False, "vision", False),
        ("Analyze this image and write Python code to extract the detected objects.", {}, True, "vision", False),
        ("Analyze this image and write Python code to extract the detected objects.", {}, False, "vision", True),
        ("Write a Python function to resize an image.", {}, False, "coding", False),
        ("There is rust on the pipe flange, is it serious?", {}, False, "general_reasoning", False),
        ("What are the ASME code requirements for pressure vessels?", {}, False, "general_reasoning", False),
        ("How does sodium react with water?", {}, False, "general_reasoning", False),
        ("Fix this React component that re-renders forever.", {}, False, "coding", False),
        ("Explain the function of a relief valve.", {}, False, "general_reasoning", False),
        ("Which component is the largest?", {"image_available": True, "last_reason": "vision"}, False, "vision", False),
        ("Which component is the largest?", {}, False, "general_reasoning", False),
        ("Now write a Python script that counts them.", {"image_available": True, "last_reason": "vision"}, False, "coding", False),
        ("TypeError: 'NoneType' object is not subscriptable", {}, False, "coding", False),
        ("How do I debug this?", {}, False, "coding", False),
        ("Read this handwritten document.", {}, False, "vision", True),
        ("What symbols are used in the P&ID?", {}, False, "vision", True),
        ("Summarize the key findings.", {"image_available": True}, False, "general_reasoning", False),
        ("Is this the right approach for our maintenance program?", {}, False, "general_reasoning", False),
        ("Write a Python function that returns the colour name.", {"image_available": True}, False, "coding", False),
        ("What does the drawing show?", {"image_available": True}, False, "vision", False),
    ]

    def test_cases(self):
        for message, context, has_images, reason, requires_image in self.CASES:
            with self.subTest(message=message, context=context, has_images=has_images):
                d = route_model(message, has_images=has_images, context=context)
                self.assertEqual(d["reason"], reason, d["explanation"])
                self.assertEqual(d["requires_image"], requires_image)
                self.assertTrue(d["explanation"])

    def test_negative_phrases_reported(self):
        self.assertIn("human error", route_model("Reduce human error.")["signals"]["negated"])

    def test_rules_are_data_in_separate_module(self):
        import inspect
        from . import router, routing_rules
        self.assertNotIn("re.compile", inspect.getsource(routing_rules))
        self.assertNotIn('"python"', inspect.getsource(router).lower())

    @patch("chat.model_manager.requests.Session.post")
    def test_general_topic_about_pid_is_answered_not_blocked(self, mock_post):
        mock_post.return_value = ollama_ok("A P&ID is...")
        response = self.client.post(reverse("chat"), {"message": "Explain what a P&ID is."}, format="json")
        self.assertFalse(response.data.get("needs_image", False))
        self.assertEqual(response.data["ollama_model"], "qwen3:8b")


class ConversationContextTests(APITestCase):
    """Phase C: backend conversation history, earlier images, context-aware routing (L3, L10)."""

    def post(self, body):
        return self.client.post(reverse("chat"), body, format="json")

    @patch("chat.model_manager.requests.Session.post")
    def test_history_is_sent_on_follow_up(self, mock_post):
        mock_post.return_value = ollama_ok("Federated learning trains models without sharing data.")
        first = self.post({"message": "Explain federated learning."})
        conv_id = first.data["conversation_id"]
        mock_post.return_value = ollama_ok("It protects privacy.")
        second = self.post({"message": "Why is that useful?", "conversation_id": conv_id})
        self.assertEqual(second.data["conversation_id"], conv_id)
        msgs = mock_post.call_args.kwargs["json"]["messages"]
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant", "user"])
        self.assertEqual(msgs[0]["content"], "Explain federated learning.")
        self.assertIn("without sharing data", msgs[1]["content"])
        self.assertEqual(second.data["context"]["history_messages_used"], 2)

    @patch("chat.model_manager.requests.Session.post")
    def test_follow_up_about_previous_image_reuses_it_with_vl(self, mock_post):
        mock_post.return_value = ollama_ok("A pump, a valve and a tank.")
        first = self.post({"message": "Analyze this engineering drawing.", "images": [PNG_B64]})
        self.assertEqual(first.data["ollama_model"], "qwen2.5vl:7b")
        mock_post.return_value = ollama_ok("The tank.")
        second = self.post({"message": "Which component is the largest?",
                            "conversation_id": first.data["conversation_id"]})
        self.assertEqual(second.data["ollama_model"], "qwen2.5vl:7b")
        self.assertEqual(second.data["routing"]["reason"], "vision")
        msgs = mock_post.call_args.kwargs["json"]["messages"]
        self.assertEqual(msgs[0]["images"], [PNG_B64])        # earlier image re-sent
        self.assertNotIn("images", msgs[-1])                  # nothing new attached
        self.assertEqual(second.data["context"]["reused_images"], 1)

    @patch("chat.model_manager.requests.Session.post")
    def test_text_model_gets_image_placeholder_not_image(self, mock_post):
        mock_post.return_value = ollama_ok("A pump and a valve.")
        first = self.post({"message": "Analyze this drawing.", "images": [PNG_B64]})
        mock_post.return_value = ollama_ok("def count(): ...")
        second = self.post({"message": "Now write a Python script that counts them.",
                            "conversation_id": first.data["conversation_id"]})
        self.assertEqual(second.data["ollama_model"], "qwen2.5-coder:7b")
        msgs = mock_post.call_args.kwargs["json"]["messages"]
        self.assertTrue(all("images" not in m for m in msgs))
        self.assertIn("[user attached 1 image(s)]", msgs[0]["content"])

    @patch("chat.model_manager.requests.Session.post")
    def test_unknown_conversation_starts_new_one(self, mock_post):
        mock_post.return_value = ollama_ok()
        response = self.post({"message": "hi", "conversation_id": "00000000-0000-0000-0000-000000000000"})
        self.assertNotEqual(response.data["conversation_id"], "00000000-0000-0000-0000-000000000000")
        self.assertEqual(len(mock_post.call_args.kwargs["json"]["messages"]), 1)

    @override_settings(OLLAMA_NUM_CTX=2048)
    @patch("chat.model_manager.requests.Session.post")
    def test_history_bounded_by_context_budget(self, mock_post):
        from .models import Conversation, ChatMessage
        conv = Conversation.objects.create()
        for i in range(10):
            ChatMessage.objects.create(conversation=conv, role="user", content=f"q{i} " + "x" * 900)
            ChatMessage.objects.create(conversation=conv, role="assistant", content=f"a{i} " + "y" * 900)
        mock_post.return_value = ollama_ok()
        response = self.post({"message": "latest?", "conversation_id": str(conv.id)})
        ctx = response.data["context"]
        self.assertTrue(ctx["history_truncated"])
        self.assertLess(ctx["history_messages_used"], 12)
        msgs = mock_post.call_args.kwargs["json"]["messages"]
        self.assertEqual(msgs[-1]["content"], "latest?")
        self.assertTrue(msgs[-2]["content"].startswith("a9"))  # newest history kept
        self.assertLess(sum(len(m["content"]) for m in msgs) / 3.0, 2048)

    @patch("chat.model_manager.requests.Session.post")
    def test_needs_image_turn_recorded_and_conversation_endpoint(self, mock_post):
        first = self.post({"message": "Analyze this P&ID."})
        conv_id = first.data["conversation_id"]
        mock_post.return_value = ollama_ok("Pumps and valves.")
        self.post({"message": "Analyze this P&ID.", "images": [PNG_B64], "conversation_id": conv_id})
        detail = self.client.get(reverse("conversation-detail", kwargs={"pk": conv_id}))
        msgs = detail.data["conversation"]["messages"]
        self.assertEqual(len(msgs), 4)
        self.assertIn("attach", msgs[1]["content"])
        self.assertEqual(len(msgs[2]["images"]), 1)
        self.assertEqual(msgs[3]["model"], "qwen2.5vl:7b")
        listing = self.client.get(reverse("conversation-list"))
        self.assertEqual(listing.data["conversations"][0]["id"], conv_id)

    @patch("chat.model_manager.requests.Session.post")
    def test_deleting_conversation_removes_image_files(self, mock_post):
        import os
        from .models import ChatAttachment
        mock_post.return_value = ollama_ok()
        conv_id = self.post({"message": "Describe this image.", "images": [PNG_B64]}).data["conversation_id"]
        path = ChatAttachment.objects.get().file.path
        self.assertTrue(os.path.isfile(path))
        self.client.delete(reverse("conversation-detail", kwargs={"pk": conv_id}))
        self.assertFalse(os.path.isfile(path))

    def test_cleanup_command_conversations(self):
        from django.core.management import call_command
        from .models import Conversation
        Conversation.objects.create(title="old test")
        out = io.StringIO()
        call_command("cleanup_dev_data", "--conversations", "--all", stdout=out)
        self.assertIn("Dry run", out.getvalue())
        call_command("cleanup_dev_data", "--conversations", "--all", "--yes", stdout=io.StringIO())
        self.assertEqual(Conversation.objects.count(), 0)


class OCRVisionIntegrationTests(APITestCase):
    """Phase E: when chat images use OCR, the vision model, or both (L25)."""

    OCR = {"text": "Finding 1: shell corrosion\nRecommendation: UT mapping in 30 days",
           "lines": 2, "confidence": 0.97, "complex_layout": False}

    def post(self, body):
        return self.client.post(reverse("chat"), body, format="json")

    @patch("documents.ocr.ocr_image")
    @patch("chat.model_manager.requests.Session.post")
    def test_document_text_task_uses_ocr_then_qwen3(self, mock_post, mock_ocr):
        mock_ocr.return_value = self.OCR
        mock_post.return_value = ollama_ok("Key finding: shell corrosion.")
        response = self.post({"message": "Summarize this inspection report and list the key findings.",
                              "images": [PNG_B64]})
        self.assertEqual(response.data["routing"]["reason"], "ocr_text")
        self.assertEqual(response.data["ollama_model"], "qwen3:8b")
        self.assertEqual(response.data["ocr"][0]["confidence"], 0.97)
        msgs = mock_post.call_args.kwargs["json"]["messages"]
        self.assertNotIn("images", msgs[-1])
        self.assertIn("shell corrosion", msgs[-1]["content"])
        mock_ocr.assert_called_once()
        # Follow-up: the OCR text travels with the history, the UI never shows it.
        mock_post.return_value = ollama_ok("UT mapping within 30 days.")
        self.post({"message": "What is the recommended action?", "conversation_id": response.data["conversation_id"]})
        history = mock_post.call_args.kwargs["json"]["messages"]
        self.assertIn("UT mapping in 30 days", history[0]["content"])
        shown = self.client.get(reverse("conversation-detail", kwargs={"pk": response.data["conversation_id"]}))
        self.assertNotIn("OCR TEXT", shown.data["conversation"]["messages"][0]["content"])

    @patch("documents.ocr.ocr_image")
    @patch("chat.model_manager.requests.Session.post")
    def test_visual_task_skips_ocr(self, mock_post, mock_ocr):
        mock_post.return_value = ollama_ok("A red pump.")
        response = self.post({"message": "Describe this image.", "images": [PNG_B64]})
        self.assertEqual(response.data["routing"]["reason"], "vision")
        mock_ocr.assert_not_called()
        self.assertIsNone(response.data["ocr"])

    @patch("documents.ocr.ocr_image")
    @patch("chat.model_manager.requests.Session.post")
    def test_text_and_visual_task_sends_image_and_ocr_to_vl(self, mock_post, mock_ocr):
        mock_ocr.return_value = self.OCR
        mock_post.return_value = ollama_ok("...")
        response = self.post({"message": "Summarize the report and describe the diagram on it.",
                              "images": [PNG_B64]})
        self.assertEqual(response.data["routing"]["reason"], "vision_ocr")
        self.assertEqual(response.data["ollama_model"], "qwen2.5vl:7b")
        last = mock_post.call_args.kwargs["json"]["messages"][-1]
        self.assertEqual(last["images"], [PNG_B64])
        self.assertIn("OCR TEXT OF ATTACHED IMAGE 1", last["content"])

    @patch("documents.ocr.ocr_image", side_effect=Exception("boom"))
    @patch("chat.model_manager.requests.Session.post")
    def test_ocr_failure_is_clean(self, mock_post, mock_ocr):
        from documents.ocr import OCRError
        mock_ocr.side_effect = OCRError("engine unavailable")
        response = self.post({"message": "Transcribe the text in this image.", "images": [PNG_B64]})
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertIn("Local OCR failed", response.data["error"])
        mock_post.assert_not_called()
