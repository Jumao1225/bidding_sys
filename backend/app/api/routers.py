from fastapi import APIRouter
from app.api.endpoints import analysis, mineru, chat, document
from app.api import sse

api_router = APIRouter()

api_router.include_router(analysis.router, prefix="/analysis", tags=["analysis"])
api_router.include_router(sse.router, prefix="/sse", tags=["sse"])
api_router.include_router(mineru.router, prefix="/mineru", tags=["mineru"])
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(document.router, prefix="/documents", tags=["documents"])
