import base64
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

PNG_B64 = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16).decode()


def ollama_ok(text="ok"):
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"response": text, "done": True, "eval_count": 3}
    mock_response.raise_for_status = Mock()
    return mock_response


class ChatAPITests(APITestCase):
    def setUp(self):
        self.chat_url = reverse("chat")

    @patch("chat.model_manager.requests.post")
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
        self.assertTrue(args[0].endswith("/api/generate"))
        self.assertEqual(kwargs["json"]["prompt"], "Hello AI")
        self.assertEqual(kwargs["json"]["model"], "qwen3:8b")
        self.assertFalse(kwargs["json"]["stream"])
        self.assertNotIn("images", kwargs["json"])

    @patch("chat.model_manager.requests.post")
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

    @patch("chat.model_manager.requests.post")
    def test_omitted_model_uses_auto_routing(self, mock_post):
        mock_post.return_value = ollama_ok()
        response = self.client.post(
            self.chat_url, {"message": "Write a Python function to add two numbers."}, format="json"
        )
        self.assertEqual(response.data["model"], "qwen-coder")
        self.assertEqual(response.data["ollama_model"], "qwen2.5-coder:7b")
        self.assertEqual(response.data["routing"], {"mode": "auto", "reason": "coding"})
        self.assertEqual(mock_post.call_args.kwargs["json"]["model"], "qwen2.5-coder:7b")

    @patch("chat.model_manager.requests.post")
    def test_manual_model_overrides_router(self, mock_post):
        mock_post.return_value = ollama_ok()
        response = self.client.post(
            self.chat_url,
            {"message": "Write a Python function to add two numbers.", "model": "qwen3"},
            format="json",
        )
        self.assertEqual(response.data["model"], "qwen3")
        self.assertEqual(response.data["routing"], {"mode": "manual", "reason": "manual"})

    @patch("chat.model_manager.requests.post")
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
        self.assertEqual(mock_post.call_args.kwargs["json"]["images"], [PNG_B64])

    @patch("chat.model_manager.requests.post")
    def test_routing_returned_on_error(self, mock_post):
        mock_post.side_effect = requests.exceptions.ConnectionError()
        response = self.client.post(
            self.chat_url, {"message": "Analyze this P&ID."}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.data["model"], "qwen-vl")
        self.assertEqual(response.data["routing"]["reason"], "vision")

    @patch("chat.model_manager.requests.post")
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

    @patch("chat.model_manager.requests.post")
    def test_ollama_server_connection_error(self, mock_post):
        """Test that connection failure to Ollama returns HTTP 503."""
        mock_post.side_effect = requests.exceptions.ConnectionError("Connection refused")

        response = self.client.post(self.chat_url, {"message": "Test server down"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertFalse(response.data.get("success"))
        self.assertEqual(response.data.get("error"), "Local AI server is unavailable.")
        self.assertNotIn("Connection refused", str(response.data))

    @patch("chat.model_manager.requests.post")
    def test_ollama_server_timeout(self, mock_post):
        """Test that timeout when contacting Ollama returns HTTP 504."""
        mock_post.side_effect = requests.exceptions.Timeout("Request timed out")

        response = self.client.post(self.chat_url, {"message": "Test timeout"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_504_GATEWAY_TIMEOUT)
        self.assertFalse(response.data.get("success"))
        self.assertIn("timed out", response.data.get("error"))

    @patch("chat.model_manager.requests.post")
    def test_ollama_server_http_error(self, mock_post):
        """Test that HTTP error (e.g. 500) from Ollama returns a clean 502."""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("500 Server Error")
        mock_post.return_value = mock_response

        response = self.client.post(self.chat_url, {"message": "Test HTTP error"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertFalse(response.data.get("success"))
        self.assertEqual(
            response.data.get("error"), "The local AI model failed to process the request."
        )
        self.assertNotIn("500 Server Error", str(response.data))

    @patch("chat.model_manager.requests.post")
    def test_model_not_installed_in_ollama(self, mock_post):
        mock_response = Mock()
        mock_response.status_code = 404
        mock_post.return_value = mock_response

        response = self.client.post(
            self.chat_url, {"message": "hi", "model": "qwen-coder"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertIn("not installed", response.data["error"])

    @patch("chat.model_manager.requests.post")
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
        self.assertEqual(payload["images"], [PNG_B64])  # data: prefix stripped

    @patch("chat.model_manager.requests.post")
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

    @patch("chat.model_manager.requests.post")
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

    @patch("chat.model_manager.requests.post")
    def test_images_refused_for_text_model(self, mock_post):
        with self.assertRaises(ModelRequestError):
            ModelManager().generate("qwen-coder", "hi", images=[PNG_B64])
        mock_post.assert_not_called()

    @override_settings(OLLAMA_URL="http://127.0.0.1:11434", OLLAMA_TIMEOUT=42)
    @patch("chat.model_manager.requests.post")
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
        self.assertIn("p&id", response.data["matched"])
        self.assertEqual(self.client.post(url, {}, format="json").status_code, 400)


class ExecutionLayerTests(APITestCase):
    """Step 8: router decides WHICH model, execution layer decides HOW to call it."""

    CASES = [
        ("Explain federated learning.", "qwen3:8b", "general_reasoning"),
        ("Write a Python function to reverse a linked list.", "qwen2.5-coder:7b", "coding"),
        ("Analyze this engineering drawing.", "qwen2.5vl:7b", "vision"),
    ]

    @patch("chat.model_manager.requests.post")
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

    @patch("chat.model_manager.requests.post")
    def test_chat_api_uses_router_then_execution(self, mock_post):
        mock_post.return_value = ollama_ok("done")
        for message, tag, reason in self.CASES:
            with self.subTest(message=message):
                response = self.client.post(reverse("chat"), {"message": message}, format="json")
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertEqual(response.data["ollama_model"], tag)
                self.assertEqual(response.data["routing"], {"mode": "auto", "reason": reason})

    def test_router_contains_no_ollama_http_logic(self):
        import inspect
        from . import router
        source = inspect.getsource(router)
        self.assertNotIn("import requests", source)
        self.assertNotIn("OLLAMA_URL", source)
        self.assertNotIn("/api/generate", source)

    @override_settings(OLLAMA_URL="http://8.8.8.8:11434")
    @patch("chat.model_manager.requests.post")
    def test_public_ollama_url_is_refused(self, mock_post):
        from .model_manager import generate_response, NonLocalEndpointError
        with self.assertRaises(NonLocalEndpointError):
            generate_response("qwen3:8b", "hi")
        response = self.client.post(reverse("chat"), {"message": "hi"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.data["error"], "Local AI server is misconfigured.")
        mock_post.assert_not_called()

    @patch("chat.model_manager.requests.post")
    def test_localhost_and_lan_urls_allowed(self, mock_post):
        from .model_manager import ModelManager
        mock_post.return_value = ollama_ok()
        for url in ("http://localhost:11434", "http://127.0.0.1:11434", "http://192.168.1.50:11434"):
            with self.subTest(url=url):
                ModelManager(base_url=url).generate("qwen3", "hi")
                self.assertTrue(mock_post.call_args.args[0].startswith(url))

    def test_unknown_model_tag_rejected(self):
        from .model_manager import generate_response
        with self.assertRaises(UnknownModelError):
            generate_response("gpt-4o", "hi")
