from fastapi import APIRouter
from app.api.endpoints import analysis, mineru, chat, document, qualification, auth, admin, business
from app.api import sse

api_router = APIRouter()

api_router.include_router(analysis.router, prefix="/analysis", tags=["analysis"])
api_router.include_router(sse.router, prefix="/sse", tags=["sse"])
api_router.include_router(mineru.router, prefix="/mineru", tags=["mineru"])
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(document.router, prefix="/documents", tags=["documents"])
api_router.include_router(qualification.router, prefix="/qualifications", tags=["qualifications"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(business.router, prefix="/business", tags=["business"])
