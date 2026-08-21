import logging

from google import genai
from google.genai import types
from pydantic import ValidationError

from config import get_settings
from models.schemas import DocumentAnalysisResult


logger = logging.getLogger(__name__)


class AIServiceError(Exception):
    """Raised when the AI service fails or returns an invalid response."""


class AIService:
    def __init__(self) -> None:
        self.settings = get_settings()
        if not self.settings.ai_api_key:
            raise AIServiceError("AI API key is missing. Please configure AI_API_KEY.")
            
        self.client = genai.Client(api_key=self.settings.ai_api_key)
        logger.info("[AI] Service initialized with model: %s", self.settings.ai_model)

    def analyze_document(self, document_text: str) -> DocumentAnalysisResult:
        """Analyze document text and extract structured information."""
        prompt = (
            "You are an AI document analysis assistant. Your task is to extract specific business details "
            "from the provided document text.\n"
            "Analyze the document text and determine the following information:\n"
            "- document_type: Identify the type of document (e.g. Supplier Invoice, Utility Bill, Vendor Quotation, Payment Reminder, etc.)\n"
            "- vendor_or_company: The name of the vendor or company issuing the document.\n"
            "- reference_number: The invoice number or reference number.\n"
            "- amount: The total amount due or referenced in the document. If no amount is found, return null.\n"
            "- currency: The currency of the amount.\n"
            "- due_date: The due date for payment or action (ISO 8601 format like YYYY-MM-DD). If no due date, return null.\n"
            "- priority: Determine the priority (e.g. Low, Medium, High, Critical, Unknown).\n"
            "- short_summary: A short, concise summary of the document.\n"
            "- required_action: Any action that needs to be taken.\n"
            "- suggested_recipient: Who should receive or review this document (e.g. Finance Manager, HR).\n"
            "- confidence: A confidence score between 0.0 and 1.0 reflecting your certainty of this extraction.\n"
            "- requires_human_approval: Set to true if important or risky actions are required, or if you are unsure.\n"
            "- reasoning_summary: A short, user-facing summary of why you extracted this information.\n\n"
            "Do NOT invent information. If a field cannot be determined reliably, leave it as null.\n\n"
            f"Document Text:\n{document_text}"
        )
        
        try:
            response = self.client.models.generate_content(
                model=self.settings.ai_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=DocumentAnalysisResult,
                    temperature=0.1,
                ),
            )
            
            if not response.text:
                raise AIServiceError("AI returned an empty response.")
                
            # The response text should be a JSON string matching the schema.
            # We parse it to ensure it's valid and to enforce the confidence threshold.
            result = DocumentAnalysisResult.model_validate_json(response.text)
            
            # Enforce confidence threshold
            if result.confidence < self.settings.ai_confidence_threshold:
                result.requires_human_approval = True
                
            return result
            
        except ValidationError as exc:
            logger.error("[AI] Structured response validation failed: %s", exc)
            raise AIServiceError("AI returned an invalid structured response.") from exc
        except Exception as exc:
            logger.error("[AI] Analysis failed (model=%s): %s: %s", self.settings.ai_model, type(exc).__name__, exc)
            raise AIServiceError(f"AI analysis could not complete: {exc}") from exc
