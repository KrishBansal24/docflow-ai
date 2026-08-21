import logging
from fastapi import FastAPI

from api import health_router, documents_router, approvals_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="DocFlow AI",
    version="0.5.0",
    description="Phase 5: PDF processing with AI analysis and Notion document workflow.",
)

app.include_router(health_router)
app.include_router(documents_router)
app.include_router(approvals_router)
