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

    @override_settings(DEFAULT_CHAT_MODEL="qwen-coder")
    @patch("chat.model_manager.requests.post")
    def test_default_model_is_configurable(self, mock_post):
        mock_post.return_value = ollama_ok()
        response = self.client.post(self.chat_url, {"message": "hi"}, format="json")
        self.assertEqual(response.data["model"], "qwen-coder")
        self.assertEqual(mock_post.call_args.kwargs["json"]["model"], "qwen2.5-coder:7b")

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
