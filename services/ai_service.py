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
            "You are an AI document analysis assistant. Read the following text and extract the key information.\n"
            "Return a valid JSON object matching this schema exactly:\n"
            "{\n"
            '  "document_type": "Invoice" | "Receipt" | "Contract" | "Unknown",\n'
            '  "vendor_company": "string",\n'
            '  "reference_number": "string",\n'
            '  "amount": number,\n'
            '  "currency": "string",\n'
            '  "due_date": "YYYY-MM-DD",\n'
            '  "priority": "Low" | "Medium" | "High" | "Critical" | "Unknown",\n'
            '  "ai_summary": "string",\n'
            '  "required_action": "string",\n'
            '  "suggested_recipient": "string"\n'
            "}\n\n"
            "If a field cannot be determined, return null for it.\n\n"
            f"Document Text:\n\n{document_text}"
        )
        
        try:
            logger.info("Sending document text to Gemini AI for analysis")
            response = self.client.models.generate_content(
                model=self.settings.ai_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=DocumentAnalysisResult,
                    temperature=0.0,
                ),
            )
            
            if not response.text:
                raise AIServiceError("Received empty response from AI model.")
                
            # The response text should be a JSON string matching the schema.
            # We parse it to ensure it's valid.
            result = DocumentAnalysisResult.model_validate_json(response.text)
            
            return result
            
        except ValidationError as exc:
            logger.error("[AI] Structured response validation failed: %s", exc)
            raise AIServiceError("AI returned an invalid structured response.") from exc
        except Exception as exc:
            logger.error("[AI] Analysis failed (model=%s): %s: %s", self.settings.ai_model, type(exc).__name__, exc)
            raise AIServiceError(f"AI analysis could not complete: {exc}") from exc
