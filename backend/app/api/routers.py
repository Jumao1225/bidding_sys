from fastapi import APIRouter
from app.api.endpoints import analysis, mineru, chat, document, qualification, auth, admin, business, bid_generator, company_profile, docx_debug, bid_scorer
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
api_router.include_router(bid_generator.router, prefix="/bidding", tags=["bidding"])
api_router.include_router(company_profile.router, prefix="/company", tags=["company"])
api_router.include_router(docx_debug.router, prefix="/docx", tags=["docx"])
api_router.include_router(bid_scorer.router, prefix="/bid-scorer", tags=["标书打分"])

# 挂载全局通用原文件下载与内嵌预览端点 (支持 GET/HEAD 方式直接调取 PDF/Word 原图)
api_router.add_api_route(
    "/download/{task_id}",
    analysis.download_original_file,
    methods=["GET", "HEAD"],
    tags=["download"]
)





