"""
标书打分 API 端点 (bid_scorer.py)

提供 5 个端点：
1. POST /upload-bid — 上传投标文件（轻量解析）
2. POST /score — 触发 AI 打分
3. GET /results/{document_id} — 查询历史打分
4. GET /results/{document_id}/latest — 查询最新打分
5. GET /detail/{result_id} — 查询逐项明细
"""

import os
import uuid
from typing import List
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from sqlalchemy.orm import Session
from loguru import logger

from app.schemas.response.common import ResponseModel, success_response, error_response
from app.schemas.bid_scorer_schema import (
    ScoreBidRequest,
    RescoreCategoryRequest,
    UploadBidResponse,
    ScoreResultSummary,
    ScoreResultDetail,
    ScoreItemResponse,
    DocChunkDetailResponse,
    ChunkBatchUpdateRequest,
)
from app.services.bid_scorer_service import bid_scorer_service
from app.db.crud.bid_score import bid_score_crud
from app.db.models.user import User
from app.api import deps

router = APIRouter()


def get_db():
    """数据库会话依赖注入"""
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================================================
# 1. 上传投标文件（轻量解析：parse + chunk + embedding）
# ============================================================

@router.post("/upload-bid", response_model=ResponseModel[dict])
async def upload_bid_document(
    file: UploadFile = File(..., description="上传的投标文件 (Word/PDF)"),
    source_doc_id: str = Form(..., description="关联的招标文件 Document ID（评分维度来源）"),
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    上传投标文件并执行轻量解析（只做 parse + chunk + embedding，不跑分析流水线）。

    前置条件：source_doc_id 对应的招标文件必须已完成解析，且 evaluation_metadata.score_tree 非空。

    返回:
        document_id: 投标文件的唯一 ID，后续传给 /score 端点使用
        chunk_count: 切片数量
        parse_status: 解析状态
    """
    # 参数校验
    if not file.filename:
        raise HTTPException(status_code=400, detail="未提供有效的文件名")

    # 校验扩展名
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in [".pdf", ".docx", ".doc"]:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式 '{ext}'，仅支持 .pdf, .docx, .doc",
        )

    if not source_doc_id or not source_doc_id.strip():
        raise HTTPException(status_code=400, detail="缺少关联的招标文件 ID (source_doc_id)")

    try:
        # 保存投标文件到专属物理目录 (uploads/bids)
        base_dir = Path(__file__).resolve().parent.parent.parent.parent
        upload_dir = os.path.join(base_dir, "uploads", "bids")
        os.makedirs(upload_dir, exist_ok=True)

        file_id = str(uuid.uuid4())[:8]
        safe_filename = f"bid_{file_id}_{file.filename}"
        file_path = os.path.join(upload_dir, safe_filename)

        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(status_code=400, detail="文件内容为空")

        with open(file_path, "wb") as f:
            f.write(file_bytes)

        logger.info(f"📤 投标文件已保存: {file_path}")

        # 调用 Service 层执行轻量解析
        result = bid_scorer_service.upload_and_parse_bid(
            db=db,
            file_path=file_path,
            filename=file.filename,
            source_doc_id=source_doc_id.strip(),
            user_id=current_user.id,
            tenant_id=current_user.tenant_id,
        )

        return success_response(data=result, message="投标文件上传解析成功")

    except ValueError as e:
        logger.warning(f"⚠️ 投标文件上传失败: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"❌ 投标文件上传异常: {e}")
        raise HTTPException(status_code=500, detail=f"投标文件处理失败: {str(e)}")


# ============================================================
# 2. 人工切片与章节标注 (Human Annotation Endpoints)
# ============================================================

@router.get("/chunks/{document_id}", response_model=ResponseModel[List[DocChunkDetailResponse]])
async def get_document_chunks(
    document_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    获取指定投标文档的所有解析切片列表（包含内容、页码与预测章节标题），
    供前端界面渲染原文及人工章节标注面板。
    """
    try:
        chunks = bid_scorer_service.get_document_chunks_for_annotation(
            db=db,
            document_id=document_id,
            user_id=current_user.id,
            tenant_id=current_user.tenant_id,
        )
        return success_response(data=chunks, message="获取切片列表成功")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception(f"❌ 获取切片失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取切片列表失败: {str(e)}")


@router.put("/chunks/{document_id}/batch-update", response_model=ResponseModel[dict])
async def update_document_chunks(
    document_id: str,
    body: ChunkBatchUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    保存人工修改或重组后的切片与章节标注数据，
    后端将批量更新向量 Embedding，确保后续 AI 打分 100% 依据人工确认后的章节维度进行检索。
    """
    try:
        result = bid_scorer_service.save_human_annotated_chunks(
            db=db,
            document_id=document_id,
            chunk_updates=body.chunks,
            user_id=current_user.id,
            tenant_id=current_user.tenant_id,
        )
        return success_response(data=result, message="人工标注切片保存成功")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"❌ 保存切片标注失败: {e}")
        raise HTTPException(status_code=500, detail=f"保存切片标注失败: {str(e)}")


# ============================================================
# 3. 触发 AI 打分
# ============================================================

@router.post("/score", response_model=ResponseModel[dict])
async def score_bid(
    request: ScoreBidRequest,
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    触发对指定投标文件的 AI 打分。

    使用 BidScorerAgent (Map-Reduce Pipeline) 进行多维度评分，
    默认执行 3 轮打分取中位数。
    """
    try:
        logger.info(
            f"🎯 [API] 触发打分: document_id={request.document_id}, "
            f"source_doc_id={request.source_doc_id}, "
            f"rounds={request.scoring_rounds}"
        )

        result = bid_scorer_service.score_bid(
            document_id=request.document_id,
            source_doc_id=request.source_doc_id,
            user_id=current_user.id,
            tenant_id=current_user.tenant_id,
            scoring_rounds=request.scoring_rounds,
        )

        if result.get("status") == "failed":
            return error_response(
                code=500,
                message=f"打分失败: {result.get('error', '未知错误')}",
                data=result,
            )

        return success_response(data=result, message="AI 打分完成")

    except Exception as e:
        logger.exception(f"❌ [API] 打分异常: {e}")
        raise HTTPException(status_code=500, detail=f"打分过程异常: {str(e)}")


# ============================================================
# 3. 查询历史打分结果
# ============================================================

@router.get("/results/{document_id}", response_model=ResponseModel[list])
async def get_score_results(
    document_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """获取指定投标文件的所有历史打分结果（按时间倒序）"""
    try:
        results = bid_score_crud.get_score_results_by_document(
            db=db,
            document_id=document_id,
            tenant_id=current_user.tenant_id,
        )

        data = [
            {
                "id": r.id,
                "document_id": r.document_id,
                "source_doc_id": r.source_doc_id,
                "evaluation_method": r.evaluation_method,
                "total_score": r.total_score,
                "max_possible": r.max_possible,
                "score_rate": r.score_rate,
                "scoring_rounds": r.scoring_rounds,
                "model_name": r.model_name,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in results
        ]

        return success_response(data=data, message=f"共 {len(data)} 条打分记录")

    except Exception as e:
        logger.exception(f"❌ 查询打分历史失败: {e}")
        raise HTTPException(status_code=500, detail="查询打分历史失败")


# ============================================================
# 4. 查询最新打分结果
# ============================================================

@router.get("/results/{document_id}/latest", response_model=ResponseModel[dict])
async def get_latest_score(
    document_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """获取指定投标文件的最新一次打分结果（含摘要和改进建议，不含逐项明细）"""
    try:
        result = bid_score_crud.get_latest_score(
            db=db,
            document_id=document_id,
            tenant_id=current_user.tenant_id,
        )

        if not result:
            raise HTTPException(status_code=404, detail="暂无打分记录")

        data = {
            "id": result.id,
            "document_id": result.document_id,
            "source_doc_id": result.source_doc_id,
            "evaluation_method": result.evaluation_method,
            "total_score": result.total_score,
            "max_possible": result.max_possible,
            "score_rate": result.score_rate,
            "category_scores": result.category_scores,
            "summary": result.summary,
            "top_improvements": result.top_improvements,
            "validation_warnings": result.validation_warnings,
            "scoring_rounds": result.scoring_rounds,
            "model_name": result.model_name,
            "created_at": result.created_at.isoformat() if result.created_at else None,
        }

        return success_response(data=data)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"❌ 查询最新打分失败: {e}")
        raise HTTPException(status_code=500, detail="查询最新打分失败")


# ============================================================
# 5. 查询逐项明细
# ============================================================

@router.get("/detail/{result_id}", response_model=ResponseModel[dict])
async def get_score_detail(
    result_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """获取某次打分的完整详情（含逐项明细）"""
    try:
        result = bid_score_crud.get_score_result_by_id(
            db=db,
            result_id=result_id,
            tenant_id=current_user.tenant_id,
        )

        if not result:
            raise HTTPException(status_code=404, detail="打分记录不存在")

        # 获取逐项明细（通过 selectin 已预加载）
        items_data = [
            {
                "id": item.id,
                "item_code": item.item_code,
                "category": item.category,
                "sub_category": item.sub_category,
                "title": item.title,
                "max_score": item.max_score,
                "ai_score": item.ai_score,
                "confidence": item.confidence,
                "score_variance": item.score_variance,
                "all_round_scores": item.all_round_scores,
                "scoring_basis": item.scoring_basis,
                "deduction_reason": item.deduction_reason,
                "suggestion": item.suggestion,
            }
            for item in result.score_items
        ]

        data = {
            "id": result.id,
            "document_id": result.document_id,
            "source_doc_id": result.source_doc_id,
            "evaluation_method": result.evaluation_method,
            "total_score": result.total_score,
            "max_possible": result.max_possible,
            "score_rate": result.score_rate,
            "category_scores": result.category_scores,
            "summary": result.summary,
            "top_improvements": result.top_improvements,
            "validation_warnings": result.validation_warnings,
            "scoring_rounds": result.scoring_rounds,
            "model_name": result.model_name,
            "created_at": result.created_at.isoformat() if result.created_at else None,
            "items": items_data,
        }

        return success_response(data=data)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"❌ 查询打分详情失败: {e}")
        raise HTTPException(status_code=500, detail="查询打分详情失败")


# ============================================================
# 6. 手动清空特定投标文件解析缓存及结果
# ============================================================

@router.delete("/document/{document_id}", response_model=ResponseModel[dict])
async def delete_bid_document(
    document_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    允许前端测试或实验员彻底删除一份指定文件的缓存（包含切片与对应的打分历史），
    支持在更新分块准则或重置流水线后，清理出完全纯洁的空间一键重练。
    """
    try:
        from app.db.models.project import Document, DocChunk
        from app.db.models.bid_score import BidScoreResult
        logger.info(f"🗑️ 收到删除标书解析与打分残留强拆指令: document_id={document_id}")
        
        doc = db.query(Document).filter(
            Document.id == document_id,
            Document.tenant_id == current_user.tenant_id
        ).first()
        
        if not doc:
            # 兼容处理：可能已经由数据库脚本手动清走，直接报成功即可
            return success_response(data={"deleted": True}, message="文件记录不在或已被安全清除")
            
        # 联动删除切片
        db.query(DocChunk).filter(DocChunk.document_id == document_id).delete()
        # 联动删除以往报告
        db.query(BidScoreResult).filter(BidScoreResult.document_id == document_id).delete()
        
        db.delete(doc)
        db.commit()
        logger.info(f"✅ 文件完全解雇回收成功: {document_id}")
        return success_response(data={"deleted": True, "document_id": document_id}, message="成功洗涤该文件全部痕迹与历史")
    except Exception as e:
        db.rollback()
        logger.exception(f"❌ 强制卸任清退文稿过程发生崩溃: {e}")
        raise HTTPException(status_code=500, detail=f"擦除非物理缓存失败: {str(e)}")


# ============================================================
# 7. 触发开源 Ragas 框架评测 (Faithfulness / Context Recall / Answer Relevance)
# ============================================================

@router.post("/evaluate-ragas/{result_id}", response_model=ResponseModel[dict])
async def evaluate_ragas_for_result(
    result_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    触发对特定打分报告的开源 Ragas 全量指标评估：
    计算 Faithfulness (防幻觉忠实度)、Answer Relevance (评语相关度)、Context Recall (召回率)。
    """
    try:
        from app.services.ragas_eval_service import ragas_eval_service
        logger.info(f"📊 [API] 触发 Ragas 开源评估: result_id={result_id}")
        eval_summary = ragas_eval_service.evaluate_score_result(db=db, score_result_id=result_id)
        return success_response(data=eval_summary, message="Ragas 开源指标评估计算完成")
    except ValueError as e:
        raise HTTPException(status_code=44, detail=str(e))
    except Exception as e:
        logger.exception(f"❌ 执行 Ragas 开源评估发生异常: {e}")
        raise HTTPException(status_code=500, detail=f"Ragas 评估算法计算失败: {str(e)}")


# ============================================================
# 8. 交互式微调与重算 (Human-in-the-Loop Rescore)
# ============================================================

@router.post("/rescore-category", response_model=ResponseModel[dict])
async def rescore_category(
    body: RescoreCategoryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """
    针对特定评估维度应用用户自定义微调指令重新打分，
    并实时更新数据库记录，返回刷新后的打分详情。
    """
    try:
        logger.info(
            f"🎯 [API] 触发维度微调重算: result_id={body.result_id}, "
            f"category={body.category}, 指令='{body.user_instruction[:30]}'"
        )

        updated_result = bid_scorer_service.rescore_category_with_instruction(
            db=db,
            result_id=body.result_id,
            category=body.category,
            item_code=body.item_code,
            user_instruction=body.user_instruction,
            tenant_id=current_user.tenant_id,
            scoring_rounds=body.scoring_rounds,
        )

        if not updated_result:
            raise HTTPException(status_code=404, detail="重算失败，记录不存在")

        # 格式化逐项明细
        items_data = [
            {
                "id": item.id,
                "item_code": item.item_code,
                "category": item.category,
                "sub_category": item.sub_category,
                "title": item.title,
                "max_score": item.max_score,
                "ai_score": item.ai_score,
                "confidence": item.confidence,
                "score_variance": item.score_variance,
                "all_round_scores": item.all_round_scores,
                "scoring_basis": item.scoring_basis,
                "deduction_reason": item.deduction_reason,
                "suggestion": item.suggestion,
            }
            for item in updated_result.score_items
        ]

        data = {
            "id": updated_result.id,
            "document_id": updated_result.document_id,
            "source_doc_id": updated_result.source_doc_id,
            "evaluation_method": updated_result.evaluation_method,
            "total_score": updated_result.total_score,
            "max_possible": updated_result.max_possible,
            "score_rate": updated_result.score_rate,
            "category_scores": updated_result.category_scores,
            "summary": updated_result.summary,
            "top_improvements": updated_result.top_improvements,
            "validation_warnings": updated_result.validation_warnings,
            "scoring_rounds": updated_result.scoring_rounds,
            "model_name": updated_result.model_name,
            "created_at": updated_result.created_at.isoformat() if updated_result.created_at else None,
            "items": items_data,
        }

        return success_response(data=data, message=f"[{body.category}] 交互微调重算完成！")

    except ValueError as e:
        logger.warning(f"⚠️ 微调重算校验参数失败: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"❌ 微调重算异常: {e}")
        raise HTTPException(status_code=500, detail=f"微调重算失败: {str(e)}")

