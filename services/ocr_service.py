import asyncio
import logging

from mistralai.client import Mistral

from config import get_settings

logger = logging.getLogger(__name__)


class OCRServiceError(Exception):
    """Raised when the OCR service fails to extract text."""


class OCRService:
    def __init__(self) -> None:
        self.settings = get_settings()
        if not self.settings.mistral_api_key:
            raise OCRServiceError(
                "Mistral API key is missing. Please configure MISTRAL_API_KEY to enable OCR."
            )
        self.client = Mistral(api_key=self.settings.mistral_api_key)

    async def extract_text(self, file_bytes: bytes, filename: str) -> str:
        """Extract text from an image or scanned PDF using Mistral OCR asynchronously."""

        def _upload_and_process() -> str:
            uploaded_file = None
            try:
                # 1. Upload file to Mistral
                uploaded_file = self.client.files.upload(
                    file={"file_name": filename, "content": file_bytes},
                    purpose="ocr",
                )

                # 2. Get signed URL to pass to the OCR endpoint
                signed_url = self.client.files.get_signed_url(file_id=uploaded_file.id)

                # 3. Process the document with Mistral OCR
                ocr_response = self.client.ocr.process(
                    model="mistral-ocr-latest",
                    document={
                        "type": "document_url",
                        "document_url": signed_url.url,
                    },
                )

                # 4. Combine markdown from all pages
                pages = ocr_response.pages
                extracted_markdown = "\n\n".join(
                    page.markdown
                    for page in pages
                    if hasattr(page, "markdown") and page.markdown
                )

                logger.info(
                    "Mistral OCR complete for %s | pages=%d | chars=%d",
                    filename,
                    len(pages),
                    len(extracted_markdown),
                )
                return extracted_markdown

            except Exception as exc:
                logger.error(
                    "Mistral OCR processing failed for %s: %s", filename, type(exc).__name__
                )
                raise OCRServiceError(f"Mistral OCR failed: {exc}") from exc
            finally:
                if uploaded_file:
                    try:
                        self.client.files.delete(file_id=uploaded_file.id)
                    except Exception as del_exc:
                        logger.warning(
                            "Failed to delete Mistral file %s: %s", uploaded_file.id, del_exc
                        )

        # Run the synchronous Mistral client in a threadpool to stay async
        return await asyncio.to_thread(_upload_and_process)
