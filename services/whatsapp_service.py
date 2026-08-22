import logging
import httpx
from typing import Any

from config import get_settings

logger = logging.getLogger(__name__)

class WhatsAppServiceError(Exception):
    pass


class WhatsAppService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.api_url = f"https://api.twilio.com/2010-04-01/Accounts/{self.settings.twilio_account_sid}/Messages.json"
        
    def _is_configured(self) -> bool:
        return bool(
            self.settings.twilio_account_sid 
            and self.settings.twilio_auth_token 
            and self.settings.twilio_whatsapp_number
        )

    async def send_message(self, to_number: str, body: str) -> dict[str, Any] | None:
        """Send a WhatsApp message via Twilio."""
        if not self._is_configured():
            logger.warning("WhatsApp service is not configured. Skipping WhatsApp send.")
            return None

        # Ensure numbers have 'whatsapp:' prefix
        if not to_number.startswith("whatsapp:"):
            to_number = f"whatsapp:{to_number}"
            
        from_number = self.settings.twilio_whatsapp_number
        if from_number and not from_number.startswith("whatsapp:"):
            from_number = f"whatsapp:{from_number}"

        data = {
            "To": to_number,
            "From": from_number,
            "Body": body
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    self.api_url,
                    data=data,
                    auth=(self.settings.twilio_account_sid, self.settings.twilio_auth_token) # type: ignore
                )
            
            if response.is_error:
                error_msg = response.text
                logger.error("[WHATSAPP] Failed to send message to %s: %s", to_number, error_msg)
                raise WhatsAppServiceError(f"Twilio API error: {error_msg}")
                
            logger.info("[WHATSAPP] Successfully sent message to %s", to_number)
            return response.json()
            
        except httpx.RequestError as exc:
            logger.error("[WHATSAPP] Network error while sending message: %s", exc)
            raise WhatsAppServiceError(f"Network error: {exc}") from exc

    async def send_approval_notification(self, to_number: str, document_name: str, notes: str | None) -> None:
        body = f"✅ Your document *{document_name}* has been approved and sent to the respective department."
        if notes:
            body += f"\n\n*Reviewer Notes:*\n_{notes}_"
        await self.send_message(to_number, body)
        
    async def send_correction_notification(self, to_number: str, document_name: str, notes: str | None) -> None:
        body = f"⚠️ Your document *{document_name}* requires some correction."
        if notes:
            body += f"\n\n*Reviewer Notes:*\n_{notes}_"
        else:
            body += "\n\nPlease review and resubmit."
        await self.send_message(to_number, body)
        
    async def send_status_reply(self, to_number: str, status: str, filename: str) -> None:
        body = f"📄 *{filename}*\nStatus: {status}"
        await self.send_message(to_number, body)
