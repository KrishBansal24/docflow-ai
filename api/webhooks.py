from typing import Any
import httpx
from fastapi import APIRouter, Request, BackgroundTasks, Form, HTTPException, UploadFile, File

from services.document_service import DocumentService
from services.whatsapp_service import WhatsAppService
from services.email_service import EmailService
from utils.hashing import calculate_file_hash
from config import get_settings
import re
import logging

logger = logging.getLogger(__name__)

router = APIRouter()
document_service = DocumentService()
whatsapp_service = WhatsAppService()
email_service = EmailService()
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


async def process_email_document_bg(media_content: bytes, filename: str, file_hash: str, sender: str) -> None:
    """Background task to process an emailed document and send an email reply."""
    try:
        await document_service.process_unique_document(media_content, filename, file_hash, sender=sender)
        email_service.send_message(
            sender, 
            "Document Processed", 
            "✅ Your document has been successfully processed and added to the Notion processing queue."
        )
    except Exception as e:
        logger.error(f"[WEBHOOK] Email bg processing failed for {filename}: {e}")
        email_service.send_message(
            sender, 
            "Document Processing Failed", 
            "⚠️ Oops! Something went wrong while processing your document. Our team has been notified."
        )


@router.post("/email")
async def email_inbound_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict[str, str]:
    """Cloudmailin endpoint for inbound email attachments."""
    form_data = await request.form()
    
    # Extract sender
    sender = form_data.get("envelope[from]") or form_data.get("from") or "Unknown Sender"
    match = re.search(r'<([^>]+)>', str(sender))
    if match:
        sender = match.group(1)
        
    # Find the first PDF attachment
    attachment = None
    for key, value in form_data.items():
        if hasattr(value, "filename") and value.filename:
            if value.content_type == "application/pdf" or str(value.filename).lower().endswith(".pdf"):
                attachment = value
                break
                
    if not attachment:
        return {"status": "ignored_no_pdf"}
        
    content = await attachment.read()
    filename = attachment.filename or "email_attachment.pdf"
    file_hash = calculate_file_hash(content)
    
    # Send immediate acknowledgement
    try:
        email_service.send_message(sender, "Document Received", "⏳ Your document has been received!\nProcessing via AI and syncing to Notion...")
    except Exception as e:
        logger.warning(f"Could not send email ack to {sender}: {e}")
        
    background_tasks.add_task(process_email_document_bg, content, filename, file_hash, sender)
    return {"status": "processing_started"}
