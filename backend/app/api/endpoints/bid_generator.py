"""
标书撰写与投标文件格式提取 API 路由模块。

暴露 API Endpoint:
- GET|POST /extract-bid-format/{document_id}           — 提取《投标文件格式》原始模板
- GET|POST /fill-bid-format/{document_id}              — 纯净导出（不自动填报）
- GET /fill-bid-format/{document_id}/audit-report      — Agent 填报审计报告
- POST /human-fill-bid-format/{document_id}             — 拟人化 Agent 填报
- GET /human-fill-bid-format/{document_id}/download     — 下载拟人化填报结果
- POST /agent-fill-bid-format/{document_id}             — BidFillerAgent (ReAct) 填报
- GET /agent-fill-bid-format/{document_id}/download     — 下载 ReAct Agent 填报结果
"""

import os
import io
import tempfile
import uuid
import urllib.parse
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from loguru import logger

from app.api import deps
from app.db.models.user import User
from app.services.bid_format_extractor_service import bid_format_extractor_service

router = APIRouter()


@router.get("/extract-bid-format/{document_id}")
@router.post("/extract-bid-format/{document_id}")
@router.get("/extract-bid-format/{document_id}/download")
async def extract_and_download_bid_format(
    document_id: str,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user)
):
    """
    定位提取招投标原始文档中的“投标文件格式/响应格式”全量内容，并自动导出为 Word (.docx) 文件供下载。
    """
    if not document_id:
        raise HTTPException(status_code=400, detail="未提供有效的 document_id 参数")

    logger.info(f"收到投标文件格式提取请求: doc_id={document_id}, user_id={current_user.id}")

    try:
        docx_bytes, filename, mode = bid_format_extractor_service.extract_and_export_bid_format(
            db=db,
            doc_id=document_id,
            user_id=current_user.id if hasattr(current_user, 'id') else None,
            tenant_id=current_user.tenant_id if hasattr(current_user, 'tenant_id') else None
        )

        if not docx_bytes:
            raise HTTPException(status_code=500, detail="未提取到有效内容或 Word 生成失败")

        encoded_filename = urllib.parse.quote(filename)

        headers = {
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
            "X-Extraction-Mode": mode,
            "Access-Control-Expose-Headers": "Content-Disposition, X-Extraction-Mode"
        }

        return Response(
            content=docx_bytes,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers=headers
        )

    except HTTPException:
        raise
    except FileNotFoundError as e:
        logger.warning(f"提取文件未找到: {str(e)}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception(f"提取并导出投标文件格式发生未预期的异常: {str(e)}")
        raise HTTPException(status_code=500, detail=f"提取生成失败: {str(e)}")


@router.get("/fill-bid-format/{document_id}")
@router.post("/fill-bid-format/{document_id}")
async def fill_and_download_bid_format(
    document_id: str,
    request_data: Optional[dict] = None,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user)
):
    """
    提取并导出 100% 原汁原味的《投标文件格式》Word (.docx) 文档。
    已移除破坏排版的自动填报改写逻辑，确保导出的格式文档与招标原文完全一致。
    """
    if not document_id:
        raise HTTPException(status_code=400, detail="未提供有效的 document_id 参数")

    logger.info(f"收到投标文件格式纯净导出请求: doc_id={document_id}")

    try:
        # 纯净提取原始《投标文件格式》Word 字节流
        template_bytes, filename, mode = bid_format_extractor_service.extract_and_export_bid_format(
            db=db,
            doc_id=document_id,
            user_id=current_user.id if hasattr(current_user, 'id') else None,
            tenant_id=current_user.tenant_id if hasattr(current_user, 'tenant_id') else None
        )

        if not template_bytes:
            raise HTTPException(status_code=500, detail="未提取到原始格式模版")

        output_filename = f"【投标文件格式】{filename}"
        encoded_filename = urllib.parse.quote(output_filename)

        headers = {
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
            "X-Extraction-Mode": mode,
            "Access-Control-Expose-Headers": "Content-Disposition, X-Extraction-Mode"
        }

        return Response(
            content=template_bytes,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers=headers
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"导出投标文件格式发生未预期异常: {str(e)}")
        raise HTTPException(status_code=500, detail=f"投标文件格式导出失败: {str(e)}")


@router.get("/fill-bid-format/{document_id}/audit-report")
async def get_bid_fill_audit_report(
    document_id: str,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user)
):
    """
    获取 Agent 标书填报对齐追溯核查报告 (Filling Audit Trail Report)
    """
    from app.schemas.bid_filler_schema import CompanyProfile
    from app.agents.bid_filler_agent import bid_filler_agent
    from app.services.bid_format_filler_service import bid_format_filler_service

    template_bytes, filename, _ = bid_format_extractor_service.extract_and_export_bid_format(
        db=db,
        doc_id=document_id,
        user_id=current_user.id if hasattr(current_user, 'id') else None,
        tenant_id=current_user.tenant_id if hasattr(current_user, 'tenant_id') else None
    )

    if not template_bytes:
        raise HTTPException(status_code=404, detail="未找到该文档的模版信息")

    # Agent 自行通过 OfficeCLI 阅读 Word 文档发现需要填写的位置，无需预扫描
    _, audit_report, _ = bid_filler_agent.process_filling_tasks(
        db=db,
        document_id=document_id,
        profile=CompanyProfile(),
        detected_placeholders=[],  # Agent 不依赖预扫描，自行发现
        original_docx=template_bytes,
    )

    return audit_report


@router.post("/human-fill-bid-format/{document_id}",
    deprecated=True,
    description="已废弃，内部已委托给方案 C BidFillerAgent 处理")
async def trigger_human_like_bid_filling(
    document_id: str,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user)
):
    """
    【已废弃】内部已委托给方案 C BidFillerAgent（LangGraph ReAct Agent）。
    """
    if not document_id:
        raise HTTPException(status_code=400, detail="未提供有效的 document_id 参数")

    logger.info(f"收到标书自动填报请求（→ 内部委托方案 C BidFillerAgent）: doc_id={document_id}")

    template_bytes, filename, _ = bid_format_extractor_service.extract_and_export_bid_format(
        db=db,
        doc_id=document_id,
        user_id=current_user.id if hasattr(current_user, 'id') else None,
        tenant_id=current_user.tenant_id if hasattr(current_user, 'tenant_id') else None
    )

    if not template_bytes:
        raise HTTPException(status_code=500, detail="未找到该文档的模版信息")

    # 委托方案 C BidFillerAgent 执行全自主标书撰写
    from app.schemas.bid_filler_schema import CompanyProfile
    from app.agents.bid_filler_agent import bid_filler_agent

    # 清理旧结果文件（防止 download 读到过期数据；文件被占用时跳过）
    drafts_dir = os.path.join(os.getcwd(), "uploads", "drafts")
    old_result = os.path.join(drafts_dir, f"human_fill_result_{document_id[:8]}.docx")
    if os.path.exists(old_result):
        try:
            os.remove(old_result)
            logger.info(f"   🧹 已清理旧结果文件: {old_result}")
        except PermissionError:
            logger.warning(f"   ⚠️ 旧结果文件被占用，将覆盖写入: {old_result}")

    logger.info("   🤖 启动 BidFillerAgent（方案 C）自主阅读文档 + 专家撰写...")
    _, audit_report, filled_bytes = bid_filler_agent.process_filling_tasks(
        db=db,
        document_id=document_id,
        profile=CompanyProfile(),
        detected_placeholders=[],
        original_docx=template_bytes,
    )

    # 将工作副本重命名为最终结果（Agent 直接在副本上修改，无需二次保存）
    working_path = os.path.join(drafts_dir, f"bid_fill_{document_id[:8]}.docx")
    result_path = os.path.join(drafts_dir, f"human_fill_result_{document_id[:8]}.docx")
    if os.path.exists(working_path):
        try:
            if os.path.exists(result_path):
                os.remove(result_path)
            os.rename(working_path, result_path)
            logger.info(f"   💾 工作副本已重命名为最终结果: {result_path}")
        except (PermissionError, OSError) as e:
            # 重命名失败时降级为复制
            logger.warning(f"   ⚠️ 重命名失败({e})，降级为复制")
            if filled_bytes:
                with open(result_path, "wb") as f:
                    f.write(filled_bytes)

    return {
        "document_id": document_id,
        "backend": "BidFillerAgent (方案 C — LangGraph ReAct Agent)",
        "audit_report": audit_report.model_dump() if audit_report else None,
        "summary": "BidFillerAgent 已完成全自主标书撰写（自主阅读 → 查库 → 专家撰写 → 写盘）",
    }


@router.get("/human-fill-bid-format/{document_id}/download",
    deprecated=True,
    description="已废弃，请使用 /agent-fill-bid-format/{document_id}/download")
async def download_human_filled_bid_format(
    document_id: str,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user)
):
    """
    获取拟人化 Agent 自动填报完成后的 Word (.docx) 文档二进制流。
    优先命中后端已导出的最终文件缓存，实现毫秒级即时下载，避免重复触发大模型 Agent。
    """
    if not document_id:
        raise HTTPException(status_code=400, detail="未提供有效的 document_id 参数")

    logger.info(f"收到拟人化 Agent 标书填报 Word 下载请求: doc_id={document_id}")

    # 优先读取 trigger 端点已持久化的结果文件，避免重复执行流水线
    drafts_dir = os.path.join(os.getcwd(), "uploads", "drafts")
    result_path = os.path.join(drafts_dir, f"human_fill_result_{document_id[:8]}.docx")
    if os.path.exists(result_path):
        logger.info(f"   📄 命中 trigger 端点已生成的结果文件: {result_path}")
        with open(result_path, "rb") as f:
            filled_bytes = f.read()
        _, raw_filename, _ = bid_format_extractor_service.extract_and_export_bid_format(
            db=db, doc_id=document_id,
            user_id=current_user.id if hasattr(current_user, 'id') else None,
            tenant_id=current_user.tenant_id if hasattr(current_user, 'tenant_id') else None
        )
        out_filename = f"【已填报】{raw_filename or '投标文件格式.docx'}"
        return Response(
            content=filled_bytes,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{urllib.parse.quote(out_filename)}",
                "Access-Control-Expose-Headers": "Content-Disposition"
            }
        )

    # 未找到结果文件，触发完整填报流水线
    template_bytes, filename, _ = bid_format_extractor_service.extract_and_export_bid_format(
        db=db,
        doc_id=document_id,
        user_id=current_user.id if hasattr(current_user, 'id') else None,
        tenant_id=current_user.tenant_id if hasattr(current_user, 'tenant_id') else None
    )

    if not template_bytes:
        raise HTTPException(status_code=500, detail="未找到该文档的模版信息")

    # 兜底：委托方案 C BidFillerAgent 执行并保存结果
    from app.schemas.bid_filler_schema import CompanyProfile
    from app.agents.bid_filler_agent import bid_filler_agent

    _, audit_report, filled_bytes = bid_filler_agent.process_filling_tasks(
        db=db,
        document_id=document_id,
        profile=CompanyProfile(),
        detected_placeholders=[],
        original_docx=template_bytes,
    )

    if not filled_bytes:
        raise HTTPException(status_code=500, detail="BidFillerAgent 填报 Word 生成失败")

    # 持久化供后续请求复用
    drafts_dir = os.path.join(os.getcwd(), "uploads", "drafts")
    os.makedirs(drafts_dir, exist_ok=True)
    result_path = os.path.join(drafts_dir, f"human_fill_result_{document_id[:8]}.docx")
    with open(result_path, "wb") as f:
        f.write(filled_bytes)

    out_filename = f"【已填报】{filename}"
    return Response(
        content=filled_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{urllib.parse.quote(out_filename)}",
            "Access-Control-Expose-Headers": "Content-Disposition"
        }
    )


# ============================================================
# BidFillerAgent (LangGraph + ReAct Agent) 自动填报端点
# ============================================================

@router.post("/agent-fill-bid-format/{document_id}")
async def trigger_agent_bid_filling(
    document_id: str,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user)
):
    """
    触发 BidFillerAgent (LangGraph + ReAct Agent) 自动填报。
    Agent 自主决策调用数据库查询工具 + OfficeCLI MCP 工具，智能填充《投标文件格式》中的空白占位符。
    """
    if not document_id:
        raise HTTPException(status_code=400, detail="未提供有效的 document_id 参数")

    logger.info(f"🤖 收到 BidFillerAgent ReAct 自动填报请求: doc_id={document_id}")

    # 1. 提取《投标文件格式》模板
    template_bytes, filename, _ = bid_format_extractor_service.extract_and_export_bid_format(
        db=db,
        doc_id=document_id,
        user_id=current_user.id if hasattr(current_user, 'id') else None,
        tenant_id=current_user.tenant_id if hasattr(current_user, 'tenant_id') else None
    )
    if not template_bytes:
        raise HTTPException(status_code=500, detail="未提取到《投标文件格式》模板，无法触发 Agent 填报")

    # 2. 扫描占位符 + 运行 BidFillerAgent
    from app.schemas.bid_filler_schema import CompanyProfile
    from app.agents.bid_filler_agent import bid_filler_agent
    from app.services.bid_format_filler_service import bid_format_filler_service

    logger.info("   🤖 Agent 将自行阅读 Word 文档并撰写内容...")

    replacement_map, audit_report, filled_bytes = bid_filler_agent.process_filling_tasks(
        db=db,
        document_id=document_id,
        profile=CompanyProfile(),
        detected_placeholders=[],  # Agent 自主发现，不依赖预扫描
        original_docx=template_bytes,
    )

    # 3. 持久化填报结果到 drafts 目录（供 download 端点直接读取，避免重复执行）
    if not filled_bytes:
        from app.services.bid_format_filler_service import bid_format_filler_service as filler_svc
        filled_bytes = filler_svc.fill_docx_with_audit_trail(
            docx_bytes=template_bytes,
            replacement_map=replacement_map,
            audit_items=audit_report.audit_items if audit_report else []
        )

    if filled_bytes:
        drafts_dir = os.path.join(os.getcwd(), "uploads", "drafts")
        os.makedirs(drafts_dir, exist_ok=True)
        result_path = os.path.join(drafts_dir, f"agent_fill_result_{document_id[:8]}.docx")
        with open(result_path, "wb") as f:
            f.write(filled_bytes)
        logger.info(f"   💾 已保存填报结果至: {result_path}")

    return {
        "document_id": document_id,
        "audit_report": audit_report.model_dump() if audit_report else None,
        "summary": f"BidFillerAgent (全自主标书撰写 Agent) 已完成《投标文件格式》的撰写",
    }


@router.get("/agent-fill-bid-format/{document_id}/download")
async def download_agent_filled_bid_format(
    document_id: str,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user)
):
    """
    下载 BidFillerAgent (LangGraph + ReAct Agent) 自动填报完成后的 Word (.docx) 文档。
    优先命中缓存，缓存未命中则触发完整填报流水线。
    """
    if not document_id:
        raise HTTPException(status_code=400, detail="未提供有效的 document_id 参数")

    logger.info(f"🤖 收到 BidFillerAgent 填报 Word 下载请求: doc_id={document_id}")

    # 优先读取 trigger 端点已持久化的结果文件，避免重复执行流水线
    drafts_dir = os.path.join(os.getcwd(), "uploads", "drafts")
    result_path = os.path.join(drafts_dir, f"agent_fill_result_{document_id[:8]}.docx")
    if os.path.exists(result_path):
        logger.info(f"   📄 命中 trigger 端点已生成的结果文件: {result_path}")
        with open(result_path, "rb") as f:
            filled_bytes = f.read()
        _, raw_filename, _ = bid_format_extractor_service.extract_and_export_bid_format(
            db=db, doc_id=document_id,
            user_id=current_user.id if hasattr(current_user, 'id') else None,
            tenant_id=current_user.tenant_id if hasattr(current_user, 'tenant_id') else None
        )
        out_filename = f"【ReActAgent智能填报】{raw_filename or '投标文件格式.docx'}"
        return Response(
            content=filled_bytes,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{urllib.parse.quote(out_filename)}",
                "Access-Control-Expose-Headers": "Content-Disposition"
            }
        )

    # 未找到结果文件，触发完整填报流水线
    template_bytes, filename, _ = bid_format_extractor_service.extract_and_export_bid_format(
        db=db,
        doc_id=document_id,
        user_id=current_user.id if hasattr(current_user, 'id') else None,
        tenant_id=current_user.tenant_id if hasattr(current_user, 'tenant_id') else None
    )
    if not template_bytes:
        raise HTTPException(status_code=500, detail="未提取到《投标文件格式》模板")

    from app.schemas.bid_filler_schema import CompanyProfile
    from app.agents.bid_filler_agent import bid_filler_agent
    from app.services.bid_format_filler_service import bid_format_filler_service

    replacement_map, audit_report, filled_bytes = bid_filler_agent.process_filling_tasks(
        db=db,
        document_id=document_id,
        profile=CompanyProfile(),
        detected_placeholders=[],  # Agent 自主发现，不依赖预扫描
        original_docx=template_bytes,
    )

    if not filled_bytes:
        # LangGraph 内部未生成字节流时兜底合成
        filled_bytes = bid_format_filler_service.fill_docx_with_audit_trail(
            docx_bytes=template_bytes,
            replacement_map=replacement_map,
            audit_items=audit_report.audit_items if audit_report else []
        )

    if not filled_bytes:
        raise HTTPException(status_code=500, detail="BidFillerAgent 填报 Word 生成失败")

    out_filename = f"【ReActAgent智能填报】{filename}"
    return Response(
        content=filled_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{urllib.parse.quote(out_filename)}",
            "Access-Control-Expose-Headers": "Content-Disposition"
        }
    )
