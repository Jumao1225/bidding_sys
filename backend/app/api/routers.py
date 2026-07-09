from fastapi import APIRouter
from app.api.endpoints import analysis
from app.api import sse

api_router = APIRouter()

api_router.include_router(analysis.router, prefix="/analysis", tags=["analysis"])
api_router.include_router(sse.router, prefix="/sse", tags=["sse"])
