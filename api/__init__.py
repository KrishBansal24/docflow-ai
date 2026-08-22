from api.health import router as health_router
from api.documents import router as documents_router
from api.approvals import router as approvals_router
from api.webhooks import router as webhooks_router

__all__ = ["health_router", "documents_router", "approvals_router", "webhooks_router"]
