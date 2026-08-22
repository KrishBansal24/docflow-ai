import logging
from fastapi import FastAPI

from api import health_router, documents_router, approvals_router, webhooks_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

import asyncio
from contextlib import asynccontextmanager

from services.approval_service import ApprovalService

async def poll_notion_approvals():
    approval_service = ApprovalService()
    while True:
        try:
            await approval_service.process_notion_updates()
        except Exception as e:
            logger.error("Polling error: %s", e)
        await asyncio.sleep(30)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Notion Poller...")
    task = asyncio.create_task(poll_notion_approvals())
    yield
    task.cancel()

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
