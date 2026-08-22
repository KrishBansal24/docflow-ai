import logging
from fastapi import FastAPI

from api import health_router, documents_router, approvals_router, webhooks_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

import asyncio
from contextlib import asynccontextmanager

from services.approval_service import ApprovalService
from services.imap_service import IMAPService
from services.email_service import EmailService
from services.document_service import DocumentService
from utils.hashing import calculate_file_hash

async def poll_notion_approvals():
    approval_service = ApprovalService()
    while True:
        try:
            await approval_service.process_notion_updates()
        except Exception as e:
            logger.error("Polling error: %s", e)
        await asyncio.sleep(1)

async def poll_inbound_emails():
    imap_service = IMAPService()
    email_service = EmailService()
    document_service = DocumentService()
    
    while True:
        try:
            pdfs = await asyncio.to_thread(imap_service.fetch_unread_pdfs)
            for pdf in pdfs:
                async def _handle_pdf(pdf_dict=pdf):
                    sender = pdf_dict["sender"]
                    filename = pdf_dict["filename"]
                    content = pdf_dict["content"]
                    file_hash = calculate_file_hash(content)
                    
                    logger.info(f"[IMAP] Found new document from {sender}: {filename}")
                    
                    try:
                        await asyncio.to_thread(email_service.send_message, sender, "Document Received", "⏳ Your document has been received!\nProcessing via AI and syncing to Notion...")
                    except Exception as e:
                        logger.warning(f"Failed to send email ack to {sender}: {e}")
                        
                    try:
                        await document_service.process_unique_document(content, filename, file_hash, sender=sender)
                        await asyncio.to_thread(
                            email_service.send_message,
                            sender, 
                            "Document Processed", 
                            "✅ Your document has been successfully processed and added to the Notion processing queue."
                        )
                    except Exception as e:
                        logger.error(f"[IMAP] processing failed for {filename}: {e}")
                        await asyncio.to_thread(
                            email_service.send_message,
                            sender, 
                            "Document Processing Failed", 
                            "⚠️ Oops! Something went wrong while processing your document. Our team has been notified."
                        )
                
                asyncio.create_task(_handle_pdf())
        except Exception as e:
            logger.error("IMAP Polling error: %s", e)
            
        await asyncio.sleep(3)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Notion Poller...")
    task1 = asyncio.create_task(poll_notion_approvals())
    logger.info("Starting IMAP Poller...")
    task2 = asyncio.create_task(poll_inbound_emails())
    yield
    task1.cancel()
    task2.cancel()

app = FastAPI(
    title="DocFlow AI",
    version="0.6.0",
    description="Phase 6: Omnichannel Document Workflow with WhatsApp and Webhooks.",
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(documents_router)
app.include_router(approvals_router)
app.include_router(webhooks_router, prefix="/webhooks", tags=["Webhooks"])
