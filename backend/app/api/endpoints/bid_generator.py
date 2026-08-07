"""
标书撰写与投标文件格式提取 API 路由模块。

暴露 API Endpoint:
- GET /documents-list                                       — 获取可用的招标文件列表
- GET /fill-bid-format/{document_id}/worker-logs            — 查取 Worker Agent 履历
- GET /fill-bid-format/{document_id}/audit-report           — Agent 填报审计报告
- GET /agent-fill-bid-format/{document_id}/download        — 下载 ReAct Agent 填报结果
- GET|POST /extract-bid-format/{document_id}              — 提取《投标文件格式》原始模板
- GET|POST /fill-bid-format/{document_id}                 — 纯净导出（不自动填报）
- POST /agent-fill-bid-format/{document_id}                — BidFillerAgent (ReAct) 填报
"""

import os
import io
import json
import time
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
from app.schemas.bid_filler_schema import BidFillRequest
from app.services.bid_format_extractor_service import bid_format_extractor_service

router = APIRouter()


# ============================================================
# 1. 静态及特定多层子路径 Endpoint (必须位于单层 {document_id} 之前)
# ============================================================

@router.get("/documents-list")
def get_bidding_documents_list(
    db: Session = Depends(deps.get_db),
    current_user: Optional[User] = Depends(deps.get_current_user_optional)
):
    """
    获取系统中已上传并解析的全套招标文件列表，供前端智能撰写控制台下拉框选择
    """
    from app.db.crud.document import document_crud
    user_id = current_user.id if current_user else None
    tenant_id = current_user.tenant_id if current_user else None
    
    docs = document_crud.get_all_documents(db, user_id, tenant_id)
    if not docs or len(docs) == 0:
        docs = document_crud.get_all_documents(db, None, None)

    res = []
    for d in docs:
        pm = d.parsed_metadata or {}
        proj_name = pm.get("project_name") or pm.get("title") or pm.get("name")
        proj_code = pm.get("project_code")
        
        # 尝试从关联的项目 Project 获取名称
        if not proj_name and hasattr(d, "project") and d.project:
            proj_name = d.project.name

        # 尝试从切片标题提取人类可读项目名
        if not proj_name and hasattr(d, "chunks") and d.chunks:
            for c in d.chunks[:5]:
                if c.section_title and len(c.section_title) > 2 and "目录" not in c.section_title:
                    proj_name = c.section_title
                    break

        code_str = f"[{proj_code}] " if proj_code else ""
        display_label = f"{code_str}{proj_name} ({d.filename})" if proj_name else d.filename

        res.append({
            "id": d.id,
            "filename": d.filename,
            "project_name": proj_name or d.filename,
            "project_code": proj_code or "--",
            "display_label": display_label,
            "parse_status": d.parse_status or "completed",
            "created_at": d.created_at.strftime("%Y-%m-%d %H:%M") if hasattr(d, "created_at") and d.created_at else "未知时间"
        })

    return res


@router.get("/fill-bid-format/{document_id}/worker-logs")
async def get_bid_fill_worker_logs(
    document_id: str,
    db: Session = Depends(deps.get_db),
    current_user: Optional[User] = Depends(deps.get_current_user_optional)
):
    """
    直查数据库获取全套 BidFillerWorker 子 Agent 节点真实运行履历与思考推导总结
    """
    if not document_id:
        raise HTTPException(status_code=400, detail="未提供有效的 document_id 参数")

    try:
        from app.db.models.audit import AgentAuditLog
        from sqlalchemy import desc, cast, String

        try:
            logs = (
                db.query(AgentAuditLog)
                .filter(cast(AgentAuditLog.inputs, String).like(f"%{document_id}%"))
                .order_by(desc(AgentAuditLog.created_at))
                .all()
            )
        except Exception as filter_err:
            logger.warning(f"基于 SQL LIKE 过滤 AgentAuditLog 异常, 降级全量过滤: {filter_err}")
            all_logs = db.query(AgentAuditLog).order_by(desc(AgentAuditLog.created_at)).limit(200).all()
            logs = [l for l in all_logs if document_id in str(l.inputs or {})]

        worker_items = []
        seen_chapters = set()

        for log in logs:
            if log.action_type in ("llm_call_worker", "llm_call_supervisor", "chapter_execution") or (log.node_name and (log.node_name.startswith("BidFillerWorker") or "Supervisor" in log.node_name)):
                inp = log.inputs or {}
                out = log.outputs or {}
                ch_title = inp.get("chapter_title") or (log.node_name.replace("BidFillerWorker-", "") if log.node_name else "未知章节")

                if ch_title in seen_chapters:
                    continue
                seen_chapters.add(ch_title)

                worker_items.append({
                    "id": str(log.id),
                    "node_name": log.node_name or f"BidFillerWorker-{ch_title}",
                    "chapter_title": ch_title,
                    "category": inp.get("category", "needs_fill"),
                    "status": log.status or "success",
                    "execution_time_ms": log.execution_time_ms or 0,
                    "total_tokens": log.total_tokens or 0,
                    "prompt_tokens": log.prompt_tokens or 0,
                    "completion_tokens": log.completion_tokens or 0,
                    "summary": out.get("summary", "已完成填报分析与写盘。"),
                    "proposals_count": out.get("proposals_count", 0),
                    "proposals": out.get("proposals", []),
                    "tools_used": out.get("tools_used", inp.get("tools_used", [])),
                    "thought_steps": out.get("thought_steps", []),
                    "created_at": log.created_at.strftime("%Y-%m-%d %H:%M:%S") if log.created_at else None
                })

        return {
            "document_id": document_id,
            "total_workers_count": len(worker_items),
            "worker_items": worker_items
        }
    except Exception as e:
        logger.exception(f"获取 Agent 运行日志出现异常: {e}")
        return {
            "document_id": document_id,
            "total_workers_count": 0,
            "worker_items": []
        }


@router.get("/fill-bid-format/{document_id}/stream-logs")
async def stream_bid_fill_worker_logs(
    document_id: str,
    db: Session = Depends(deps.get_db),
    current_user: Optional[User] = Depends(deps.get_current_user_optional)
):
    """
    通过 SSE (Server-Sent Events) 实时推流获取 BidFillerWorker 全套 Agent 节点运行履历与 CoT 思维链
    """
    if not document_id:
        raise HTTPException(status_code=400, detail="未提供有效的 document_id 参数")

    async def log_event_generator():
        import asyncio
        import time
        from app.db.models.audit import AgentAuditLog
        from sqlalchemy import desc, cast, String
        from app.db.session import SessionLocal

        last_json = None
        same_count = 0

        while True:
            session: Session = SessionLocal()
            try:
                try:
                    logs = (
                        session.query(AgentAuditLog)
                        .filter(cast(AgentAuditLog.inputs, String).like(f"%{document_id}%"))
                        .order_by(desc(AgentAuditLog.created_at))
                        .all()
                    )
                except Exception:
                    all_logs = session.query(AgentAuditLog).order_by(desc(AgentAuditLog.created_at)).limit(200).all()
                    logs = [l for l in all_logs if document_id in str(l.inputs or {})]

                worker_items = []
                seen_chapters = set()
                all_completed = True if logs else False

                for log in logs:
                    if log.action_type in ("llm_call_worker", "llm_call_supervisor", "chapter_execution") or (log.node_name and (log.node_name.startswith("BidFillerWorker") or "Supervisor" in log.node_name)):
                        inp = log.inputs or {}
                        out = log.outputs or {}
                        ch_title = inp.get("chapter_title") or (log.node_name.replace("BidFillerWorker-", "") if log.node_name else "未知章节")

                        if ch_title in seen_chapters:
                            continue
                        seen_chapters.add(ch_title)

                        status_val = log.status or "success"
                        if status_val == "in_progress":
                            all_completed = False

                        worker_items.append({
                            "id": str(log.id),
                            "node_name": log.node_name or f"BidFillerWorker-{ch_title}",
                            "chapter_title": ch_title,
                            "category": inp.get("category", "needs_fill"),
                            "status": status_val,
                            "execution_time_ms": log.execution_time_ms or 0,
                            "total_tokens": log.total_tokens or 0,
                            "prompt_tokens": log.prompt_tokens or 0,
                            "completion_tokens": log.completion_tokens or 0,
                            "summary": out.get("summary", "已完成填报分析与写盘。"),
                            "proposals_count": out.get("proposals_count", 0),
                            "proposals": out.get("proposals", []),
                            "tools_used": out.get("tools_used", inp.get("tools_used", [])),
                            "thought_steps": out.get("thought_steps", []),
                            "created_at": log.created_at.strftime("%Y-%m-%d %H:%M:%S") if log.created_at else None
                        })

                payload = {
                    "document_id": document_id,
                    "worker_items": worker_items,
                    "is_completed": all_completed and len(worker_items) > 0,
                    "timestamp": time.time()
                }
                payload_str = json.dumps(payload, ensure_ascii=False)

                if payload_str != last_json:
                    last_json = payload_str
                    same_count = 0
                    yield f"data: {payload_str}\n\n"
                else:
                    same_count += 1
                    yield f": ping {int(time.time())}\n\n"

                if all_completed and len(worker_items) > 0 and same_count >= 5:
                    break

            except Exception as e:
                logger.error(f"SSE 推流日志生成异常: {e}")
            finally:
                session.close()

            await asyncio.sleep(1.0)

    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        log_event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive"
        }
    )


@router.get("/fill-bid-format/{document_id}/audit-report")
async def get_bid_fill_audit_report(
    document_id: str,
    db: Session = Depends(deps.get_db),
    current_user: Optional[User] = Depends(deps.get_current_user_optional)
):
    """
    获取 Agent 标书填报对齐追溯核查报告 (Filling Audit Trail Report)
    包含字段级对齐报告 + 数据库保存的子 Agent 真实思考与执行履历
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

    # Agent 自行通过 OfficeCLI 阅读 Word 文档发现需要填写的位置
    _, audit_report, _ = bid_filler_agent.process_filling_tasks(
        db=db,
        document_id=document_id,
        profile=CompanyProfile(),
        detected_placeholders=[],
        original_docx=template_bytes,
    )

    res_dict = audit_report.model_dump() if hasattr(audit_report, 'model_dump') else audit_report.dict()

    # 融合直查数据库得到的子 Agent 思考全过程履历
    try:
        worker_logs = await get_bid_fill_worker_logs(document_id=document_id, db=db, current_user=current_user)
        res_dict["worker_items"] = worker_logs.get("worker_items", [])
        res_dict["total_workers_count"] = worker_logs.get("total_workers_count", 0)
    except Exception as exc:
        logger.warning(f"获取 Worker 审计日志融合失败: {exc}")
        res_dict["worker_items"] = []
        res_dict["total_workers_count"] = 0

    return res_dict


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
    """
    if not document_id:
        raise HTTPException(status_code=400, detail="未提供有效的 document_id 参数")

    logger.info(f"收到拟人化 Agent 标书填报 Word 下载请求: doc_id={document_id}")

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

    template_bytes, filename, _ = bid_format_extractor_service.extract_and_export_bid_format(
        db=db,
        doc_id=document_id,
        user_id=current_user.id if hasattr(current_user, 'id') else None,
        tenant_id=current_user.tenant_id if hasattr(current_user, 'tenant_id') else None
    )

    if not template_bytes:
        raise HTTPException(status_code=500, detail="未找到该文档的模版信息")

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


@router.get("/agent-fill-bid-format/{document_id}/download")
async def download_agent_filled_bid_format(
    document_id: str,
    db: Session = Depends(deps.get_db),
    current_user: Optional[User] = Depends(deps.get_current_user_optional)
):
    """
    下载 BidFillerAgent (LangGraph + ReAct Agent) 自动填报完成后的 Word (.docx) 文档。
    """
    if not document_id:
        raise HTTPException(status_code=400, detail="未提供有效的 document_id 参数")

    logger.info(f"🤖 收到 BidFillerAgent 填报 Word 下载请求: doc_id={document_id}")

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
        detected_placeholders=[],
        original_docx=template_bytes,
    )

    if not filled_bytes:
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


# ============================================================
# 2. 单层通用参数 Endpoint (必须位于多层子路径之后)
# ============================================================

@router.get("/extract-bid-format/{document_id}")
@router.post("/extract-bid-format/{document_id}")
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
    """
    if not document_id:
        raise HTTPException(status_code=400, detail="未提供有效的 document_id 参数")

    logger.info(f"收到投标文件格式纯净导出请求: doc_id={document_id}")

    try:
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


@router.post("/human-fill-bid-format/{document_id}",
    deprecated=True,
    description="已废弃，内部已委托给方案 C BidFillerAgent 处理")
async def trigger_human_like_bid_filling(
    document_id: str,
    request_body: Optional[BidFillRequest] = None,
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

    from app.schemas.bid_filler_schema import CompanyProfile
    from app.agents.bid_filler_agent import bid_filler_agent

    custom_instructions = None
    category_hints = None
    if request_body:
        custom_instructions = request_body.custom_instructions
        category_hints = request_body.category_hints

    drafts_dir = os.path.join(os.getcwd(), "uploads", "drafts")
    old_result = os.path.join(drafts_dir, f"human_fill_result_{document_id[:8]}.docx")
    if os.path.exists(old_result):
        try:
            os.remove(old_result)
        except PermissionError:
            pass

    _, audit_report, filled_bytes = bid_filler_agent.process_filling_tasks(
        db=db,
        document_id=document_id,
        profile=CompanyProfile(),
        detected_placeholders=[],
        original_docx=template_bytes,
        custom_instructions=custom_instructions,
        category_hints=category_hints,
    )

    working_path = os.path.join(drafts_dir, f"bid_fill_{document_id[:8]}.docx")
    result_path = os.path.join(drafts_dir, f"human_fill_result_{document_id[:8]}.docx")
    if os.path.exists(working_path):
        try:
            if os.path.exists(result_path):
                os.remove(result_path)
            os.rename(working_path, result_path)
        except (PermissionError, OSError):
            if filled_bytes:
                with open(result_path, "wb") as f:
                    f.write(filled_bytes)

    return {
        "document_id": document_id,
        "backend": "BidFillerAgent (方案 C — LangGraph ReAct Agent)",
        "audit_report": audit_report.model_dump() if audit_report else None,
        "summary": "BidFillerAgent 已完成全自主标书撰写",
    }


@router.post("/agent-fill-bid-format/{document_id}")
def trigger_agent_bid_filling(
    document_id: str,
    request_body: Optional[BidFillRequest] = None,
    db: Session = Depends(deps.get_db),
    current_user: Optional[User] = Depends(deps.get_current_user_optional)
):
    """
    触发 BidFillerAgent (LangGraph + ReAct Agent) 自动填报。
    """
    if not document_id:
        raise HTTPException(status_code=400, detail="未提供有效的 document_id 参数")

    logger.info(f"🤖 收到 BidFillerAgent ReAct 自动填报请求: doc_id={document_id}")

    # 建立多租户与用户安全上下文，全链路透传至 ContextVar 及多线程 Worker
    from app.core.context import current_user_id, current_tenant_id
    u_id = current_user.id if (current_user and hasattr(current_user, 'id')) else "default-user"
    t_id = current_user.tenant_id if (current_user and hasattr(current_user, 'tenant_id')) else "default-tenant"
    token_u = current_user_id.set(u_id)
    token_t = current_tenant_id.set(t_id)

    custom_instructions = None
    category_hints = None
    if request_body:
        custom_instructions = request_body.custom_instructions
        category_hints = request_body.category_hints

    # 清理该文档上一次的填报审计日志，为全新一轮运行提供实时卡片弹增与追溯空间
    try:
        from app.db.models.audit import AgentAuditLog
        old_logs = db.query(AgentAuditLog).all()
        for l in old_logs:
            if l.inputs and isinstance(l.inputs, dict) and l.inputs.get("document_id") == document_id:
                db.delete(l)
        db.commit()
    except Exception as del_err:
        logger.warning(f"清理旧 AuditLog 异常: {del_err}")

    template_bytes, filename, _ = bid_format_extractor_service.extract_and_export_bid_format(
        db=db,
        doc_id=document_id,
        user_id=current_user.id if hasattr(current_user, 'id') else None,
        tenant_id=current_user.tenant_id if hasattr(current_user, 'tenant_id') else None
    )
    if not template_bytes:
        raise HTTPException(status_code=500, detail="未提取到《投标文件格式》模板，无法触发 Agent 填报")

    from app.schemas.bid_filler_schema import CompanyProfile
    from app.agents.bid_filler_agent import bid_filler_agent

    replacement_map, audit_report, filled_bytes = bid_filler_agent.process_filling_tasks(
        db=db,
        document_id=document_id,
        profile=CompanyProfile(),
        detected_placeholders=[],
        original_docx=template_bytes,
        custom_instructions=custom_instructions,
        category_hints=category_hints,
    )

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

    return {
        "document_id": document_id,
        "audit_report": audit_report.model_dump() if audit_report else None,
        "summary": "BidFillerAgent (全自主标书撰写 Agent) 已完成《投标文件格式》的撰写",
    }
