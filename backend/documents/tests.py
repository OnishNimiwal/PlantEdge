import io
from unittest.mock import patch, Mock
import pymupdf
import docx
import requests

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Document

def create_sample_pdf_bytes(content: str = "This is a sample MRPL report text.") -> bytes:
    """Generates valid minimal in-memory PDF bytes with text."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 72), content)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes

class DocumentAPITests(APITestCase):
    def setUp(self):
        self.upload_url = reverse("document-upload")
        self.list_url = reverse("document-list")

    def test_upload_valid_txt_file(self):
        """Test uploading a valid TXT file extracts text and creates Document."""
        txt_content = "MRPL Confidential Guidelines: All data stays on PC5."
        txt_file = SimpleUploadedFile("guidelines.txt", txt_content.encode("utf-8"), content_type="text/plain")

        response = self.client.post(self.upload_url, {"file": txt_file}, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["document"]["original_name"], "guidelines.txt")
        self.assertEqual(response.data["document"]["file_type"], "TXT")
        self.assertIn("MRPL Confidential Guidelines", response.data["document"]["extracted_text"])

    def test_upload_valid_pdf_file(self):
        """Test uploading a valid PDF extracts text via PyMuPDF."""
        pdf_bytes = create_sample_pdf_bytes("Phase 2 local document assistant operational verification.")
        pdf_file = SimpleUploadedFile("report.pdf", pdf_bytes, content_type="application/pdf")

        response = self.client.post(self.upload_url, {"file": pdf_file}, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["document"]["file_type"], "PDF")
        self.assertIn("Phase 2 local document assistant", response.data["document"]["extracted_text"])

    def test_reject_unsupported_extensions(self):
        """Test that extensions like .docx, .xlsx, .jpg, .png are rejected."""
        bad_files = [
            ("data.docx", b"dummy docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            ("sheet.xlsx", b"dummy xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            ("image.jpg", b"\xff\xd8\xff", "image/jpeg"),
            ("photo.png", b"\x89PNG\r\n", "image/png"),
        ]

        for filename, content, mime in bad_files:
            file_obj = SimpleUploadedFile(filename, content, content_type=mime)
            response = self.client.post(self.upload_url, {"file": file_obj}, format="multipart")
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertFalse(response.data.get("success", True))
            self.assertIn("Unsupported file type", response.data.get("error", ""))

    def test_reject_empty_file(self):
        """Test that empty TXT or PDF files are rejected with 400."""
        empty_txt = SimpleUploadedFile("empty.txt", b"", content_type="text/plain")
        response = self.client.post(self.upload_url, {"file": empty_txt}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("empty", response.data.get("error", "").lower())

    def test_character_limit_truncation(self):
        """Test that documents exceeding 50,000 characters are capped."""
        long_content = "A" * 60000
        txt_file = SimpleUploadedFile("huge.txt", long_content.encode("utf-8"), content_type="text/plain")

        response = self.client.post(self.upload_url, {"file": txt_file}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        extracted = response.data["document"]["extracted_text"]
        self.assertTrue(extracted.startswith("A" * 50000))
        self.assertIn("truncated at 50,000 characters", extracted)

    @patch("documents.services.requests.post")
    def test_ask_question_about_document(self, mock_post):
        """Test asking a question about an uploaded document."""
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"response": "The document specifies on-premise inference on PC5."}
        mock_resp.raise_for_status = Mock()
        mock_post.return_value = mock_resp

        doc = Document.objects.create(
            original_name="test.txt",
            file_type="TXT",
            extracted_text="MRPL system uses PC5 workstation with local Qwen model.",
        )

        ask_url = reverse("document-ask", kwargs={"pk": doc.id})
        response = self.client.post(ask_url, {"question": "Where does the model run?"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["answer"], "The document specifies on-premise inference on PC5.")

    @patch("documents.services.requests.post")
    def test_summarize_document(self, mock_post):
        """Test generating an AI summary of an uploaded document."""
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"response": "1. Executive Overview: Project completed successfully."}
        mock_resp.raise_for_status = Mock()
        mock_post.return_value = mock_resp

        doc = Document.objects.create(
            original_name="summary_test.txt",
            file_type="TXT",
            extracted_text="Project completed on schedule with zero cloud dependencies.",
        )

        sum_url = reverse("document-summary", kwargs={"pk": doc.id})
        response = self.client.post(sum_url, {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertIn("Executive Overview", response.data["summary"])

    @patch("documents.services.requests.post")
    def test_ollama_offline_returns_503(self, mock_post):
        """Test that Ollama connection error returns HTTP 503."""
        mock_post.side_effect = requests.exceptions.ConnectionError("Connection refused")

        doc = Document.objects.create(
            original_name="offline.txt",
            file_type="TXT",
            extracted_text="Sample text.",
        )

        ask_url = reverse("document-ask", kwargs={"pk": doc.id})
        response = self.client.post(ask_url, {"question": "Hello?"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertFalse(response.data["success"])
        self.assertIn("unavailable", response.data["error"].lower())

    def test_generate_and_download_docx_report(self):
        """Test generating a Word DOCX report returns valid docx binary."""
        doc = Document.objects.create(
            original_name="audit_report.txt",
            file_type="TXT",
            extracted_text="Detailed audit findings for MRPL infrastructure.",
        )

        report_url = reverse("document-generate-report", kwargs={"pk": doc.id})
        response = self.client.post(
            report_url,
            {"summary": "Summary: All systems meet on-premise compliance standards."},
            format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        self.assertIn("attachment; filename=", response["Content-Disposition"])

        # Parse generated docx bytes to verify valid Word document structure
        doc_stream = io.BytesIO(response.content)
        parsed_docx = docx.Document(doc_stream)
        text_content = "\n".join([p.text for p in parsed_docx.paragraphs])
        self.assertIn("MRPL AI Workbench", text_content)
        self.assertIn("audit_report.txt", [cell.text for row in parsed_docx.tables[0].rows for cell in row.cells])

    def test_delete_document(self):
        """Test deleting a document removes it from the database."""
        doc = Document.objects.create(
            original_name="delete_me.txt",
            file_type="TXT",
            extracted_text="Temp text",
        )

        detail_url = reverse("document-detail", kwargs={"pk": doc.id})
        response = self.client.delete(detail_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(Document.objects.filter(pk=doc.id).exists())

    def test_phase1_chat_still_works(self):
        """Regression test: Phase 1 /api/chat/ endpoint still works."""
        with patch("chat.model_manager.requests.post") as mock_post:
            mock_resp = Mock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"response": "Phase 1 chat response"}
            mock_resp.raise_for_status = Mock()
            mock_post.return_value = mock_resp

            response = self.client.post(
                reverse("chat"),
                {"message": "Hello chat"},
                format="json"
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertTrue(response.data["success"])
