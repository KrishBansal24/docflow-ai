from typing import Any
import httpx
from fastapi import APIRouter, Request, BackgroundTasks, Form, HTTPException, UploadFile, File

from services.document_service import DocumentService
from services.whatsapp_service import WhatsAppService
from utils.hashing import calculate_file_hash
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
                await whatsapp_service.send_message(sender, f"❌ Sorry, we couldn't download your document. Please try again later. (Error: {response.status_code})")
                return
                
            media_content = response.content
            content_type = response.headers.get("Content-Type", "application/pdf")
            
            # Determine extension
            ext = ".pdf"
            if "image/jpeg" in content_type:
                ext = ".jpg"
            elif "image/png" in content_type:
                ext = ".png"
                
            # Try to get original filename from headers
            content_disposition = response.headers.get("Content-Disposition", "")
            filename = ""
            if "filename=" in content_disposition:
                # e.g. attachment; filename="invoice.pdf"
                filename = content_disposition.split("filename=")[-1].strip('"\'')
            
            if not filename:
                filename = f"WhatsApp_Document{ext}"
            file_hash = calculate_file_hash(media_content)

        # 2. Process document. We pass sender down so it can be saved in the database
        await document_service.process_unique_document(media_content, filename, file_hash, sender=sender)
        
        # 3. Notify success
        await whatsapp_service.send_message(sender, f"✅ Your document has been successfully received and added to the Notion processing queue.")
        
    except Exception as e:
        await whatsapp_service.send_message(sender, f"⚠️ Oops! Something went wrong while processing your document. Our team has been notified.")


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
