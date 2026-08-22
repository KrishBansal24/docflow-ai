import logging
from fastapi import FastAPI

from api import health_router, documents_router, approvals_router, webhooks_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="DocFlow AI",
    version="0.6.0",
    description="Phase 6: Omnichannel Document Workflow with WhatsApp and Webhooks.",
)

app.include_router(health_router)
app.include_router(documents_router)
app.include_router(approvals_router)
app.include_router(webhooks_router, prefix="/webhooks", tags=["Webhooks"])
