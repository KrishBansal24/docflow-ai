from typing import Any
import httpx
from fastapi import APIRouter, Request, BackgroundTasks, Form, HTTPException, UploadFile, File

from services.document_service import DocumentService
from services.whatsapp_service import WhatsAppService
from config import get_settings

router = APIRouter()
document_service = DocumentService()
whatsapp_service = WhatsAppService()
settings = get_settings()


async def process_whatsapp_document_bg(media_url: str, sender: str) -> None:
    """Background task to download media from Twilio and process it."""
    try:
        # 1. Download media from Twilio
        async with httpx.AsyncClient(follow_redirects=True) as client:
            auth = (settings.twilio_account_sid, settings.twilio_auth_token) # type: ignore
            response = await client.get(media_url, auth=auth)
            
            if response.is_error:
                await whatsapp_service.send_status_reply(sender, "Failed", f"Error downloading media from Twilio: {response.status_code}")
                return
                
            media_content = response.content
            content_type = response.headers.get("Content-Type", "application/pdf")
            
            # Determine extension
            ext = ".pdf"
            if "image/jpeg" in content_type:
                ext = ".jpg"
            elif "image/png" in content_type:
                ext = ".png"
                
            filename = f"whatsapp_upload_{sender}{ext}"

        # 2. Process document
        await document_service.process_unique_document(media_content, filename, content_type)
        
        # 3. Notify success
        await whatsapp_service.send_status_reply(sender, "Success - Added to Notion", filename)
        
    except Exception as e:
        await whatsapp_service.send_status_reply(sender, "Failed", f"System Error: {str(e)}")


@router.post("/whatsapp")
async def twilio_whatsapp_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    NumMedia: str = Form("0"),
    From: str = Form(...),
) -> str:
    """Twilio WhatsApp webhook endpoint."""
    form_data = await request.form()
    
    num_media = int(NumMedia)
    if num_media == 0:
        # No media attached, just text
        await whatsapp_service.send_status_reply(From, "Error", "Please attach a document (PDF/Image) to process.")
        return "OK"
        
    media_url = form_data.get("MediaUrl0")
    if not media_url:
        return "OK"
        
    # Send immediate acknowledgement
    await whatsapp_service.send_message(From, "⏳ *Document received!*\nProcessing via AI and syncing to Notion...")
    
    # Process in background
    background_tasks.add_task(process_whatsapp_document_bg, str(media_url), From)
    
    # Twilio expects a TwiML or 200 OK text response
    return "OK"


@router.post("/email")
async def email_inbound_webhook(
    background_tasks: BackgroundTasks,
    attachment1: UploadFile = File(None)
) -> dict[str, str]:
    """Generic endpoint for inbound email attachments (e.g. via SendGrid Parse)."""
    if not attachment1:
        raise HTTPException(status_code=400, detail="No attachment found")
        
    content = await attachment1.read()
    filename = attachment1.filename or "email_attachment.pdf"
    content_type = attachment1.content_type or "application/pdf"
    
    # We could send an email reply here acknowledging receipt, but for now we just process
    # Since webhooks expect fast responses, we could push this to background.
    # For simplicity, we process it synchronously or push to bg if we had an email to reply to.
    
    async def process_email_bg() -> None:
        await document_service.process_unique_document(content, filename, content_type)
        
    background_tasks.add_task(process_email_bg)
    return {"status": "processing_started"}
