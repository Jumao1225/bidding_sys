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
from fastapi import APIRouter, Depends, HTTPException, Response, BackgroundTasks
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session
from loguru import logger

from app.api import deps
from app.db.models.user import User
from app.schemas.bid_filler_schema import BidFillRequest, RegenerateChapterRequest, RegenerateChapterResponse
from app.services.bid_format_extractor_service import bid_format_extractor_service

router = APIRouter()


# ============================================================
# 1. 静态及特定多层子路径 Endpoint (必须位于单层 {document_id} 之前)
# ============================================================

@router.get("/documents-list")
def get_bidding_documents_list(
    doc_type: Optional[str] = None,
    db: Session = Depends(deps.get_db),
    current_user: Optional[User] = Depends(deps.get_current_user_optional)
):
    """
    获取系统中已上传并解析的全套招标文件列表，供前端智能撰写控制台下拉框选择
    默认仅返回 doc_type=tender 的招标文件
    """
    from app.db.crud.document import document_crud
    user_id = current_user.id if current_user else None
    tenant_id = current_user.tenant_id if current_user else None
    
    # 默认针对标书撰写拉取仅招标文件
    target_type = doc_type if doc_type else "tender"
    
    docs = document_crud.get_all_documents(db, user_id, tenant_id, doc_type=target_type)
    if not docs or len(docs) == 0:
        docs = document_crud.get_all_documents(db, None, None, doc_type=target_type)

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
            "doc_type": pm.get("doc_type", "tender"),
            "project_name": proj_name or d.filename,
            "project_code": proj_code or "--",
            "display_label": display_label,
            "parse_status": d.parse_status or "completed",
            "created_at": d.created_at.isoformat() if hasattr(d, "created_at") and d.created_at else None
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
                .filter(
                    or_(
                        AgentAuditLog.task_id == document_id,
                        cast(AgentAuditLog.inputs, String).like(f"%{document_id}%")
                    )
                )
                .order_by(desc(AgentAuditLog.created_at))
                .all()
            )
        except Exception as filter_err:
            logger.warning(f"基于 SQL 过滤 AgentAuditLog 异常, 降级全量过滤: {filter_err}")
            all_logs = db.query(AgentAuditLog).order_by(desc(AgentAuditLog.created_at)).limit(200).all()
            logs = [l for l in all_logs if l.task_id == document_id or document_id in str(l.inputs or {})]

        worker_items = []
        seen_chapters = set()

        # 检查是否已存在正式完成的 Supervisor 记录，以便过滤掉最初的 in_progress 占位日志
        has_final_supervisor = any(
            (log.node_name and "Supervisor" in log.node_name) and log.status in ("success", "master_completed")
            for log in logs
        )

        total_wall_time_ms = 0
        min_created_at = None
        max_created_at = None

        for log in logs:
            if log.created_at:
                if min_created_at is None or log.created_at < min_created_at:
                    min_created_at = log.created_at
                if max_created_at is None or log.created_at > max_created_at:
                    max_created_at = log.created_at

            # 如果已有正式完成的 Supervisor 日志，则忽略最初纯占位的 in_progress 日志
            if has_final_supervisor and log.node_name and "Supervisor" in log.node_name and log.status == "in_progress":
                continue

            if log.status == "master_completed" and log.execution_time_ms and log.execution_time_ms > 0:
                total_wall_time_ms = max(total_wall_time_ms, log.execution_time_ms)

            if log.action_type in ("llm_call_worker", "llm_call_supervisor", "chapter_execution") or (log.node_name and (log.node_name.startswith("BidFillerWorker") or "Supervisor" in log.node_name)):
                inp = log.inputs or {}
                out = log.outputs or {}
                is_supervisor = (log.node_name and "Supervisor" in log.node_name) or log.action_type == "llm_call_supervisor"
                
                ch_title = "Supervisor 总控调度" if is_supervisor else (inp.get("chapter_title") or (log.node_name.replace("BidFillerWorker-", "") if log.node_name else "未知章节"))

                if ch_title in seen_chapters:
                    continue
                seen_chapters.add(ch_title)

                worker_items.append({
                    "id": str(log.id),
                    "node_name": "Supervisor-总控调度" if is_supervisor else (log.node_name or f"BidFillerWorker-{ch_title}"),
                    "chapter_title": ch_title,
                    "category": "supervisor_master" if is_supervisor else inp.get("category", "needs_fill"),
                    "status": log.status or "success",
                    "execution_time_ms": log.execution_time_ms or 0,
                    "total_tokens": log.total_tokens or ((log.prompt_tokens or 0) + (log.completion_tokens or 0)),
                    "prompt_tokens": log.prompt_tokens or 0,
                    "completion_tokens": log.completion_tokens or 0,
                    "summary": out.get("summary", "已完成填报分析与写盘。"),
                    "proposals_count": out.get("proposals_count", 0),
                    "proposals": out.get("proposals", []),
                    "tools_used": out.get("tools_used", inp.get("tools_used", [])),
                    "thought_steps": out.get("thought_steps", []),
                    "created_at": log.created_at.strftime("%Y-%m-%d %H:%M:%S") if log.created_at else None
                })

        total_worker_time_ms = sum(w.get("execution_time_ms", 0) for w in worker_items)
        if total_wall_time_ms == 0 and min_created_at and max_created_at:
            delta_ms = int((max_created_at - min_created_at).total_seconds() * 1000)
            if delta_ms > 0:
                total_wall_time_ms = delta_ms

        return {
            "document_id": document_id,
            "total_workers_count": len(worker_items),
            "worker_items": worker_items,
            "total_wall_time_ms": total_wall_time_ms,
            "total_worker_time_ms": total_worker_time_ms
        }
    except Exception as e:
        logger.exception(f"获取 Agent 运行日志出现异常: {e}")
        return {
            "document_id": document_id,
            "total_workers_count": 0,
            "worker_items": [],
            "total_wall_time_ms": 0,
            "total_worker_time_ms": 0
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
                        .filter(
                            or_(
                                AgentAuditLog.task_id == document_id,
                                cast(AgentAuditLog.inputs, String).like(f"%{document_id}%")
                            )
                        )
                        .order_by(desc(AgentAuditLog.created_at))
                        .all()
                    )
                except Exception:
                    all_logs = session.query(AgentAuditLog).order_by(desc(AgentAuditLog.created_at)).limit(200).all()
                    logs = [l for l in all_logs if l.task_id == document_id or document_id in str(l.inputs or {})]

                worker_items = []
                seen_chapters = set()

                has_final_supervisor = any(
                    (log.node_name and "Supervisor" in log.node_name) and log.status in ("success", "master_completed")
                    for log in logs
                )

                total_wall_time_ms = 0
                min_created_at = None
                max_created_at = None

                for log in logs:
                    if log.created_at:
                        if min_created_at is None or log.created_at < min_created_at:
                            min_created_at = log.created_at
                        if max_created_at is None or log.created_at > max_created_at:
                            max_created_at = log.created_at

                    if has_final_supervisor and log.node_name and "Supervisor" in log.node_name and log.status == "in_progress":
                        continue

                    if log.status == "master_completed" and log.execution_time_ms and log.execution_time_ms > 0:
                        total_wall_time_ms = max(total_wall_time_ms, log.execution_time_ms)

                    if log.action_type in ("llm_call_worker", "llm_call_supervisor", "chapter_execution") or (log.node_name and (log.node_name.startswith("BidFillerWorker") or "Supervisor" in log.node_name)):
                        inp = log.inputs or {}
                        out = log.outputs or {}
                        is_supervisor = (log.node_name and "Supervisor" in log.node_name) or log.action_type == "llm_call_supervisor"
                        ch_title = "Supervisor 总控调度" if is_supervisor else (inp.get("chapter_title") or (log.node_name.replace("BidFillerWorker-", "") if log.node_name else "未知章节"))

                        if ch_title in seen_chapters:
                            continue
                        seen_chapters.add(ch_title)

                        status_val = log.status or "success"

                        worker_items.append({
                            "id": str(log.id),
                            "node_name": "Supervisor-总控调度" if is_supervisor else (log.node_name or f"BidFillerWorker-{ch_title}"),
                            "chapter_title": ch_title,
                            "category": "supervisor_master" if is_supervisor else inp.get("category", "needs_fill"),
                            "status": status_val,
                            "execution_time_ms": log.execution_time_ms or 0,
                            "total_tokens": log.total_tokens or ((log.prompt_tokens or 0) + (log.completion_tokens or 0)),
                            "prompt_tokens": log.prompt_tokens or 0,
                            "completion_tokens": log.completion_tokens or 0,
                            "summary": out.get("summary", "已完成填报分析与写盘。"),
                            "proposals_count": out.get("proposals_count", 0),
                            "proposals": out.get("proposals", []),
                            "tools_used": out.get("tools_used", inp.get("tools_used", [])),
                            "thought_steps": out.get("thought_steps", []),
                            "created_at": log.created_at.strftime("%Y-%m-%d %H:%M:%S") if log.created_at else None
                        })

                total_worker_time_ms = sum(w.get("execution_time_ms", 0) for w in worker_items)
                if total_wall_time_ms == 0 and min_created_at and max_created_at:
                    delta_ms = int((max_created_at - min_created_at).total_seconds() * 1000)
                    if delta_ms > 0:
                        total_wall_time_ms = delta_ms

                # 判断所有最新状态的节点中是否还有正在进行中的任务
                has_in_progress = any(w.get("status") in ("in_progress", "running") for w in worker_items)

                # 只有当日志非空、没有任何在途进行中的 Worker、且至少有一个成功节点时才判定为全量完成
                all_completed = (
                    bool(logs) and 
                    not has_in_progress and 
                    len(worker_items) > 0 and 
                    any(w.get("status") in ("success", "master_completed") for w in worker_items)
                )

                payload = {
                    "document_id": document_id,
                    "worker_items": worker_items,
                    "is_completed": all_completed,
                    "total_wall_time_ms": total_wall_time_ms,
                    "total_worker_time_ms": total_worker_time_ms,
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


@router.post("/fill-bid-format/{document_id}/regenerate-chapter", response_model=RegenerateChapterResponse)
async def regenerate_single_chapter(
    document_id: str,
    request_body: RegenerateChapterRequest,
    db: Session = Depends(deps.get_db),
    current_user: Optional[User] = Depends(deps.get_current_user_optional)
):
    """
    针对具体指定章节重新启动 Worker Agent 进行针对性起草与 Prompt 微调，并原位写回 Word 文档。
    """
    if not document_id:
        raise HTTPException(status_code=400, detail="未提供有效的 document_id 参数")
    if not request_body.chapter_title:
        raise HTTPException(status_code=400, detail="未提供目标章节名称 chapter_title")

    chapter_title = request_body.chapter_title.strip()
    custom_prompt = (request_body.custom_prompt or "").strip()
    category = (request_body.category or "needs_fill").strip()
    mapping_hint = (request_body.mapping_hint or "").strip()

    logger.info(f"🔄 收到单章节重新生成/微调请求: doc_id={document_id}, chapter={chapter_title}, prompt='{custom_prompt[:60]}'")

    # 1. 准备 Word 工作副本与纯净原始模板
    drafts_dir = os.path.join(os.getcwd(), "uploads", "drafts")
    os.makedirs(drafts_dir, exist_ok=True)
    working_docx_path = os.path.join(drafts_dir, f"bid_fill_{document_id[:8]}.docx")
    result_docx_path = os.path.join(drafts_dir, f"agent_fill_result_{document_id[:8]}.docx")
    template_docx_path = os.path.join(drafts_dir, f"template_{document_id[:8]}.docx")

    # 确保纯净模板存在（供单章微调提取纯净无污染的占位符上下文）
    if not os.path.exists(template_docx_path):
        template_bytes, filename, _ = bid_format_extractor_service.extract_and_export_bid_format(
            db=db, doc_id=document_id, user_id=None, tenant_id=None
        )
        if template_bytes:
            with open(template_docx_path, "wb") as f:
                f.write(template_bytes)

    if not os.path.exists(working_docx_path):
        if os.path.exists(result_docx_path):
            import shutil
            shutil.copyfile(result_docx_path, working_docx_path)
        elif os.path.exists(template_docx_path):
            import shutil
            shutil.copyfile(template_docx_path, working_docx_path)

    # 2. 注入上下文变量
    from app.core.context import current_user_id, current_tenant_id, current_task_id
    u_id = current_user.id if (current_user and hasattr(current_user, 'id')) else "default-user"
    t_id = current_user.tenant_id if (current_user and hasattr(current_user, 'tenant_id')) else "default-tenant"
    token_task = current_task_id.set(document_id)
    token_u = current_user_id.set(u_id)
    token_t = current_tenant_id.set(t_id)

    # 3. 记录初始进行中状态
    try:
        from app.services.audit_service import audit_service
        audit_service.log_event(
            action_type="llm_call_worker",
            node_name=f"BidFillerWorker-{chapter_title[:30]}",
            inputs={"chapter_title": chapter_title, "category": category, "document_id": document_id, "custom_prompt": custom_prompt},
            outputs={
                "summary": f"🔄 正在根据用户提示词对章节 [{chapter_title}] 重新起草与微调...",
                "proposals_count": 0,
                "thought_steps": [
                    {"step": 1, "type": "thought", "content": f"接收到用户微调指令: '{custom_prompt}'，正在启动专属 Worker Agent 重新调取数据并生成提案。"}
                ]
            },
            status="in_progress"
        )
    except Exception as log_init_err:
        logger.warning(f"写入微调初始状态日志异常: {log_init_err}")

    try:
        from app.agents.bid_filler_workers import run_chapter_worker
        from app.agents.bid_filler_agent import fill_docx_proposals_in_dom
        from app.utils.table_utils import extract_chapter_dom_structure

        # 优先从纯净模板提取章节专属上下文，并在重新生成前将工作副本中该章节重置为纯净模板状态（确保100%覆盖）
        from app.agents.bid_filler_workers import extract_docx_tables_summary
        from app.utils.table_utils import get_chapter_specific_table_indices, reset_chapter_to_template

        if os.path.exists(template_docx_path) and os.path.exists(working_docx_path):
            reset_chapter_to_template(working_docx_path, template_docx_path, chapter_title)

        template_source_path = template_docx_path if os.path.exists(template_docx_path) else working_docx_path
        target_tbl_summary = extract_docx_tables_summary(template_source_path, chapter_title)
        
        # 组装纯净模板提示（如为表格章节，突出表头定义与全量重写要求）
        if target_tbl_summary:
            chapter_pure_context = f"【本章节专属表格表头定义】\n{target_tbl_summary}\n（请根据招标文件原文及企业数据库全量检索数据，生成完整 2D 矩阵全量覆写）"
        else:
            chapter_pure_context = extract_chapter_dom_structure(template_source_path, chapter_title)
            if not chapter_pure_context and template_source_path != working_docx_path:
                chapter_pure_context = extract_chapter_dom_structure(working_docx_path, chapter_title)
            if not chapter_pure_context:
                chapter_pure_context = f"【目标章节】: {chapter_title}"

        # 尝试从历史日志中继承该章节的分类 hint 与说明
        effective_category = category
        effective_mapping_hint = mapping_hint
        try:
            from app.db.models.audit import AgentAuditLog
            from sqlalchemy import desc
            hist_log = (
                db.query(AgentAuditLog)
                .filter(AgentAuditLog.task_id == document_id)
                .filter(AgentAuditLog.node_name == f"BidFillerWorker-{chapter_title[:30]}")
                .order_by(desc(AgentAuditLog.created_at))
                .first()
            )
            if hist_log and hist_log.inputs:
                if not effective_mapping_hint:
                    effective_mapping_hint = hist_log.inputs.get("mapping_hint", "")
                if not effective_category or effective_category == "needs_fill":
                    effective_category = hist_log.inputs.get("category", effective_category)
        except Exception:
            pass

        # 预读取企业档案与项目元数据（用于公文类单章微调定向注入）
        prefetched_metadata: Dict[str, Any] = {}
        try:
            from app.db.models.business import CompanyProfileModel
            from app.db.models.metadata import TimelineMetadata, FinancialMetadata
            from app.utils.rmb_formatter import number_to_chinese_rmb

            prof = db.query(CompanyProfileModel).first()
            if prof:
                if prof.company_name: prefetched_metadata["company_name"] = prof.company_name
                if prof.credit_code: prefetched_metadata["credit_code"] = prof.credit_code
                if prof.legal_representative: prefetched_metadata["legal_person"] = prof.legal_representative
                if prof.registered_address: prefetched_metadata["address"] = prof.registered_address
                if prof.contact_phone: prefetched_metadata["phone"] = prof.contact_phone
                if prof.email: prefetched_metadata["email"] = prof.email

            tl = db.query(TimelineMetadata).filter(TimelineMetadata.document_id == document_id).first()
            if tl:
                if getattr(tl, "project_name", None): prefetched_metadata["project_name"] = tl.project_name
                proj_code = getattr(tl, "project_id_code", None) or getattr(tl, "project_code", None)
                if proj_code: prefetched_metadata["project_code"] = proj_code
                
                period_str = str(getattr(tl, "construction_period_description", "") or "").strip()
                if not period_str and getattr(tl, "construction_period_days", None):
                    period_str = f"{tl.construction_period_days} 日历天"
                if period_str:
                    prefetched_metadata["delivery_period"] = period_str

            from app.db.models.ai_analysis import CostEstimate
            cost_items = db.query(CostEstimate).filter(CostEstimate.document_id == document_id).all()
            if cost_items:
                total_val = sum(getattr(it, "calculated_total", 0.0) or 0.0 for it in cost_items)
                if total_val > 0:
                    prefetched_metadata["total_price_str"] = f"{total_val:,.2f} 元"
                    try:
                        prefetched_metadata["total_price_words"] = number_to_chinese_rmb(float(total_val))
                    except Exception:
                        pass

            prefetched_metadata["quality_standard"] = "合格，完全符合国家及行业现行有关标准、规范要求"
        except Exception as e_meta:
            logger.warning(f"微调接口预读取企业与项目元数据异常: {e_meta}")

        start_time = time.time()
        worker_res = await run_in_threadpool(
            run_chapter_worker,
            chapter_title=chapter_title,
            chapter_number="",
            mapping_hint=effective_mapping_hint,
            category=effective_category,
            document_id=document_id,
            docx_temp_path=working_docx_path,
            template_text=chapter_pure_context,
            content_hint="（请根据招标文件原文与企业数据库检索全量数据，按要求全量重新起草与覆写本章节）",
            extra_instructions=custom_prompt or "请按照主流程标准，全量重新检索招标文件与数据库并完成全表覆写。",
            repair_instructions="",
            prefetched_metadata=prefetched_metadata,
        )
        elapsed_ms = int((time.time() - start_time) * 1000)

        proposals = worker_res.get("proposals", [])
        status = worker_res.get("status", "success")
        summary = worker_res.get("summary", "单章节微调已完成。")

        # 4. 原位刷盘
        if os.path.exists(working_docx_path):
            try:
                write_count = fill_docx_proposals_in_dom(working_docx_path, proposals) if proposals else 0
                logger.info(f"✅ 单章节微调原位写盘完成，写入 {write_count} 处修改")
                # 同步到 result 文件
                import shutil
                shutil.copyfile(working_docx_path, result_docx_path)
                draft_path = os.path.join(drafts_dir, f"draft_{document_id}.docx")
                shutil.copyfile(working_docx_path, draft_path)
            except Exception as write_err:
                logger.error(f"单章节微调写盘异常: {write_err}")

        # 5. 查询最新的 audit log 条目
        from app.db.models.audit import AgentAuditLog
        from sqlalchemy import desc, cast, String
        latest_log = (
            db.query(AgentAuditLog)
            .filter(
                or_(
                    AgentAuditLog.task_id == document_id,
                    cast(AgentAuditLog.inputs, String).like(f"%{document_id}%")
                )
            )
            .filter(
                or_(
                    AgentAuditLog.node_name == f"BidFillerWorker-{chapter_title[:30]}",
                    cast(AgentAuditLog.inputs, String).like(f"%{chapter_title}%")
                )
            )
            .order_by(desc(AgentAuditLog.created_at))
            .first()
        )

        worker_item = None
        if latest_log:
            inp = latest_log.inputs or {}
            out = latest_log.outputs or {}
            worker_item = {
                "id": str(latest_log.id),
                "node_name": latest_log.node_name or f"BidFillerWorker-{chapter_title}",
                "chapter_title": chapter_title,
                "category": inp.get("category", category),
                "status": latest_log.status or "success",
                "execution_time_ms": latest_log.execution_time_ms or elapsed_ms,
                "total_tokens": latest_log.total_tokens or 0,
                "prompt_tokens": latest_log.prompt_tokens or 0,
                "completion_tokens": latest_log.completion_tokens or 0,
                "summary": out.get("summary", summary),
                "proposals_count": out.get("proposals_count", len(proposals)),
                "proposals": out.get("proposals", proposals),
                "tools_used": out.get("tools_used", inp.get("tools_used", [])),
                "thought_steps": out.get("thought_steps", []),
                "created_at": latest_log.created_at.strftime("%Y-%m-%d %H:%M:%S") if latest_log.created_at else None
            }

        return RegenerateChapterResponse(
            document_id=document_id,
            chapter_title=chapter_title,
            status=status,
            summary=summary,
            proposals_count=len(proposals),
            execution_time_ms=elapsed_ms,
            total_tokens=worker_item.get("total_tokens", 0) if worker_item else 0,
            worker_item=worker_item
        )

    except Exception as exc:
        logger.exception(f"❌ 单章节微调失败: {exc}")
        raise HTTPException(status_code=500, detail=f"单章节重新生成失败: {str(exc)}")
    finally:
        try:
            current_task_id.reset(token_task)
            current_user_id.reset(token_u)
            current_tenant_id.reset(token_t)
        except Exception:
            pass



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
        docx_bytes, filename, mode = await run_in_threadpool(
            bid_format_extractor_service.extract_and_export_bid_format,
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
        template_bytes, filename, mode = await run_in_threadpool(
            bid_format_extractor_service.extract_and_export_bid_format,
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

    template_bytes, filename, _ = await run_in_threadpool(
        bid_format_extractor_service.extract_and_export_bid_format,
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

    _, audit_report, filled_bytes = await run_in_threadpool(
        bid_filler_agent.process_filling_tasks,
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


def _run_agent_bid_filling_in_background(
    document_id: str,
    u_id: str,
    t_id: str,
    custom_instructions: Optional[str] = None,
    category_hints: Optional[dict] = None,
):
    """后台工作线程：执行长耗时的 BidFillerAgent 多 Agent 标书撰写与落盘"""
    from app.core.context import current_user_id, current_tenant_id, current_task_id
    from app.db.session import SessionLocal
    from app.schemas.bid_filler_schema import CompanyProfile
    from app.agents.bid_filler_agent import bid_filler_agent
    from app.services.bid_format_extractor_service import bid_format_extractor_service

    token_task = current_task_id.set(document_id)
    token_u = current_user_id.set(u_id)
    token_t = current_tenant_id.set(t_id)
    db: Session = SessionLocal()
    import time as _bg_time
    bg_start_t = _bg_time.time()
    try:
        template_bytes, filename, _ = bid_format_extractor_service.extract_and_export_bid_format(
            db=db, doc_id=document_id, user_id=None, tenant_id=None
        )
        if not template_bytes:
            logger.error(f"后台任务提取《投标文件格式》模板失败: doc_id={document_id}")
            from app.db.models.audit import AgentAuditLog
            err_log = AgentAuditLog(
                task_id=document_id,
                tenant_id=t_id,
                user_id=u_id,
                node_name="Supervisor-总控调度",
                action_type="llm_call_supervisor",
                status="failed",
                inputs={"chapter_title": "Supervisor-总控调度"},
                outputs={"summary": "❌ 后台提取《投标文件格式》模板失败"}
            )
            db.add(err_log)
            db.commit()
            return

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
            draft_path = os.path.join(drafts_dir, f"draft_{document_id}.docx")
            for p in [result_path, draft_path]:
                with open(p, "wb") as f:
                    f.write(filled_bytes)
            logger.info(f"✅ 后台标书撰写完成并已保存至: {result_path}")

            # 写入 Supervisor 最终完成日志，记录端到端真实物理总耗时
            total_wall_ms = int((_bg_time.time() - bg_start_t) * 1000)
            try:
                from app.db.models.audit import AgentAuditLog
                final_sup_log = AgentAuditLog(
                    task_id=document_id,
                    tenant_id=t_id,
                    user_id=u_id,
                    node_name="Supervisor-总控调度",
                    action_type="llm_call_supervisor",
                    status="master_completed",
                    execution_time_ms=total_wall_ms,
                    inputs={"document_id": document_id, "chapter_title": "Supervisor-总控调度", "wall_time_ms": total_wall_ms},
                    outputs={"summary": f"✨ AI 团队自主撰写与原位写盘已全量收官！全流程耗时 {total_wall_ms / 1000:.1f} 秒。所有章节卡片均已更新。"}
                )
                db.add(final_sup_log)
                db.commit()
            except Exception as final_log_err:
                logger.warning(f"写入最终 Supervisor 完结日志异常: {final_log_err}")
    except Exception as e:
        logger.exception(f"❌ 后台标书撰写任务异常: {e}")
        try:
            from app.db.models.audit import AgentAuditLog
            err_log = AgentAuditLog(
                task_id=document_id,
                tenant_id=t_id,
                user_id=u_id,
                node_name="Supervisor-总控调度",
                action_type="llm_call_supervisor",
                status="failed",
                inputs={"chapter_title": "Supervisor-总控调度"},
                outputs={"summary": f"❌ 后台标书撰写任务异常中断: {str(e)}"}
            )
            db.add(err_log)
            db.commit()
        except Exception:
            pass
    finally:
        try:
            current_task_id.reset(token_task)
            current_user_id.reset(token_u)
            current_tenant_id.reset(token_t)
        except Exception:
            pass
        db.close()


@router.post("/agent-fill-bid-format/{document_id}")
async def trigger_agent_bid_filling(
    document_id: str,
    background_tasks: BackgroundTasks,
    request_body: Optional[BidFillRequest] = None,
    db: Session = Depends(deps.get_db),
    current_user: Optional[User] = Depends(deps.get_current_user_optional)
):
    """
    触发 BidFillerAgent (LangGraph + ReAct Agent) 自动填报。
    使用 BackgroundTasks 进行后台解耦，瞬间返回响应，配合 SSE (stream-logs) 获得 0 延迟卡片实时弹增体验。
    """
    if not document_id:
        raise HTTPException(status_code=400, detail="未提供有效的 document_id 参数")

    logger.info(f"🤖 收到 BidFillerAgent ReAct 自动填报请求: doc_id={document_id}")

    u_id = current_user.id if (current_user and hasattr(current_user, 'id')) else "default-user"
    t_id = current_user.tenant_id if (current_user and hasattr(current_user, 'tenant_id')) else "default-tenant"

    custom_instructions = None
    category_hints = None
    if request_body:
        custom_instructions = request_body.custom_instructions
        category_hints = request_body.category_hints

    # 清理该文档上一次的填报审计日志，并立即注入全局起始 in_progress 记录
    try:
        from app.db.models.audit import AgentAuditLog
        from sqlalchemy import cast, String
        db.query(AgentAuditLog).filter(
            or_(
                AgentAuditLog.task_id == document_id,
                cast(AgentAuditLog.inputs, String).like(f"%{document_id}%")
            )
        ).delete(synchronize_session=False)

        init_log = AgentAuditLog(
            task_id=document_id,
            tenant_id=t_id,
            user_id=u_id,
            node_name="Supervisor-总控调度",
            action_type="llm_call_supervisor",
            status="in_progress",
            inputs={"document_id": document_id, "chapter_title": "Supervisor-总控调度", "msg": "准备启动新一轮 Agent 全自主起草..."},
            outputs={"summary": "正在初始化 Agent 专家团队与指令解析..."}
        )
        db.add(init_log)
        db.commit()
        logger.info(f"成功清理旧日志并写入初始 in_progress 状态记录，doc_id={document_id}")
    except Exception as del_err:
        logger.warning(f"清理旧 AuditLog 异常: {del_err}")
        db.rollback()

    import threading
    filling_thread = threading.Thread(
        target=_run_agent_bid_filling_in_background,
        kwargs={
            "document_id": document_id,
            "u_id": u_id,
            "t_id": t_id,
            "custom_instructions": custom_instructions,
            "category_hints": category_hints
        },
        daemon=True
    )
    filling_thread.start()

    return {
        "document_id": document_id,
        "status": "processing",
        "message": "已成功启动 Agent 团队后台全自主撰写流程，请通过 SSE 实时监听进度"
    }
