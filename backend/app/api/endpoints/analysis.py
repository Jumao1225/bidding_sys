from typing import Optional, List, Dict, Any
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, BackgroundTasks, Depends
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from loguru import logger
import os
import uuid
from pathlib import Path
import glob
from datetime import datetime

from app.schemas.response.common import ResponseModel, success_response
from app.worker.tasks import analyze_bidding_doc
from app.agents.tools.metadata_tools import (
    extract_qualification_info,
    extract_financial_info,
    extract_timeline_info,
    extract_engineering_info,
    extract_evaluation_info
)

router = APIRouter()

from app.db.models.user import User
from app.api import deps

@router.post("/upload-and-analyze", response_model=ResponseModel[dict])
async def upload_and_analyze(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="上传的招标文件 (Word/PDF 等)"),
    company_quals: str = Form("", description="我方公司的资质信息文本"),
    current_user: User = Depends(deps.get_current_active_user)
):
    """
    上传招标文件，触发后台 AI 提取和对比流程。
    返回 task_id，客户端可通过 SSE 接口订阅进度。
    """
    # 1. 验证前置条件 (Early Return)
    if not file.filename:
        raise HTTPException(status_code=400, detail="未提供有效的文件名")
        
    try:
        # 生成唯一 Task ID
        task_id = str(uuid.uuid4())
        
        # 保存文件到临时目录
        base_dir = Path(__file__).resolve().parent.parent.parent.parent
        upload_dir = os.path.join(base_dir, "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        file_path = os.path.join(upload_dir, f"{task_id}_{file.filename}")
        
        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(status_code=400, detail="文件内容为空")
            
        with open(file_path, "wb") as f:
            f.write(file_bytes)
            
        logger.info(f"文件已保存: {file_path}，即将触发 Celery 任务: {task_id}")
        
        # 触发后台异步任务
        background_tasks.add_task(
            analyze_bidding_doc,
            task_id, 
            file_path, 
            file.filename, 
            company_quals,
            current_user.id,
            current_user.tenant_id
        )
        
        # 返回 task_id，前端根据这个 task_id 建立 SSE 连接
        return success_response(data={"task_id": task_id}, message="任务已提交，请通过 SSE 获取进度")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"提交分析任务失败: {str(e)}")
        raise e

def get_db():
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/{document_id}/reextract/{domain}", response_model=ResponseModel[dict])
async def reextract_domain(
    document_id: str, 
    domain: str, 
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_user)
):
    """
    针对特定的元数据领域（domain）进行重新提取，并返回最新结果。
    """
    domain_map = {
        "qualification": extract_qualification_info,
        "financial": extract_financial_info,
        "timeline": extract_timeline_info,
        "engineering": extract_engineering_info,
        "evaluation": extract_evaluation_info
    }
    
    if domain not in domain_map and domain not in ("cost_estimation", "cost", "writer", "draft", "writer_agent", "strategy_qual", "qualifications_analysis", "qual_analysis", "opening_summary", "opening_summary_agent"):
        raise HTTPException(status_code=400, detail=f"未知的提取领域: {domain}")
        
    try:
        from app.db.crud.document import document_crud
        from app.worker.tasks import emit_agent_log
        from app.core.context import current_task_id, current_user_id, current_tenant_id
        
        # 鉴权验证：确保文档属于当前用户
        doc = document_crud.get_document_by_id(db, document_id, current_user.id, current_user.tenant_id)
        if not doc:
            raise HTTPException(status_code=403, detail="无权访问该文档或文档不存在")
            
        # 为了让 emit_agent_log 生效，并满足安全鉴权，注入全链路上下文
        token_task = current_task_id.set(document_id)
        token_user = current_user_id.set(current_user.id)
        token_tenant = current_tenant_id.set(current_user.tenant_id)
        
        try:
            if domain in ("opening_summary", "opening_summary_agent"):
                from app.agents.nodes.opening_summary_agent import generate_opening_summary_node
                state = {
                    "document_id": document_id,
                    "user_id": current_user.id,
                    "tenant_id": current_user.tenant_id
                }
                summary_res = generate_opening_summary_node(state)
                doc_fresh = document_crud.get_document_by_id(db, document_id, current_user.id, current_user.tenant_id)
                fresh_meta = doc_fresh.parsed_metadata if doc_fresh else {}
                return success_response(
                    data={
                        "opening_summary_path": summary_res.get("opening_summary_path") or fresh_meta.get("opening_summary_path"),
                        "opening_summary_data": summary_res.get("summary_data") or fresh_meta.get("opening_summary_data"),
                        "status": "success"
                    },
                    message="开标一览表编写成功"
                )

            if domain in ("cost_estimation", "cost"):
                from sqlalchemy.orm.attributes import flag_modified
                from app.agents.nodes.cost_agent import cost_node
                
                state = {
                    "document_id": document_id,
                    "user_id": current_user.id,
                    "tenant_id": current_user.tenant_id
                }
                cost_result = cost_node(state)
                cost_data = cost_result.get("cost_analysis", {})
                
                # 持久化更新至数据库 parsed_metadata
                parsed_metadata = dict(doc.parsed_metadata or {})
                parsed_metadata["cost_analysis"] = cost_data
                doc.parsed_metadata = parsed_metadata
                flag_modified(doc, "parsed_metadata")
                db.commit()
                
                return success_response(data=cost_data, message="成本测算重新计算成功")

            if domain in ("strategy_qual", "qualifications_analysis", "qual_analysis"):
                from sqlalchemy.orm.attributes import flag_modified
                from app.agents.nodes.strategy_agent import analyze_qualifications_node

                state = {
                    "document_id": document_id,
                    "user_id": current_user.id,
                    "tenant_id": current_user.tenant_id,
                    "company_quals": (doc.parsed_metadata or {}).get("company_quals", "")
                }
                qual_result = analyze_qualifications_node(state)
                qual_data = qual_result.get("qualifications_analysis", {})

                parsed_metadata = dict(doc.parsed_metadata or {})
                parsed_metadata["qualifications_analysis"] = qual_data
                doc.parsed_metadata = parsed_metadata
                flag_modified(doc, "parsed_metadata")
                db.commit()

                return success_response(data=qual_data, message="资质核对与能力盘点重新计算成功")

            if domain in ("writer", "draft", "writer_agent"):
                from app.agents.bid_filler_agent import bid_filler_orchestrator_node as writer_agent_node
                state = {
                    "document_id": document_id,
                    "user_id": current_user.id,
                    "tenant_id": current_user.tenant_id,
                    "company_quals": (doc.parsed_metadata or {}).get("company_quals", "")
                }
                writer_result = writer_agent_node(state)
                
                # 重新刷新从数据库读取最新 parsed_metadata 包含的 bid_doc_outline
                doc_fresh = document_crud.get_document_by_id(db, document_id, current_user.id, current_user.tenant_id)
                fresh_meta = doc_fresh.parsed_metadata if doc_fresh else {}

                return success_response(
                    data={
                        "draft_path": writer_result.get("draft_path") or fresh_meta.get("draft_path"),
                        "bid_doc_outline": fresh_meta.get("bid_doc_outline"),
                        "status": "success"
                    },
                    message="投标书草稿重新生成成功"
                )
            
            tool_func = domain_map[domain]
            # 调用工具提取（其内部已包含落盘逻辑）
            res_str = tool_func.invoke({"document_id": document_id})
            
            import json
            if res_str and res_str.startswith("{"):
                res_data = json.loads(res_str)
                if "error" in res_data:
                    logger.error(f"重新提取 {domain} 失败: {res_data['error']}")
                    raise HTTPException(status_code=500, detail=f"重新提取失败: {res_data['error']}")
                return success_response(data=res_data, message=f"{domain} 领域重新提取成功")
            else:
                logger.error(f"重新提取 {domain} 失败或无权限: {res_str}")
                raise HTTPException(status_code=500, detail=f"重新提取失败: {res_str}")
        finally:
            current_task_id.reset(token_task)
            current_user_id.reset(token_user)
            current_tenant_id.reset(token_tenant)
            
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"重新提取 {domain} 异常: {str(e)}")
        raise HTTPException(status_code=500, detail=f"重新提取异常: {str(e)}")

from pydantic import BaseModel, Field

class CostItemUpdateRequest(BaseModel):
    name: str = Field(..., description="项目/设备名称")
    spec_requirement: str = Field(default="", description="规格或说明")
    qty: Optional[float] = Field(default=1.0, description="数量")
    unit: str = Field(default="项", description="单位")
    ref_price: float = Field(default=0.0, description="参考单价")
    matched_name: str = Field(default="", description="匹配设备名称")
    matched_brand: str = Field(default="", description="匹配品牌")
    matched_model: str = Field(default="", description="匹配型号")
    matched_manufacturer: str = Field(default="", description="匹配厂商")
    key_parameters: List[str] = Field(default_factory=list, description="关键参数")
    brand_requirements: str = Field(default="", description="品牌要求")
    match_quality: str = Field(default="手动添加", description="匹配置信度")
    warning: str = Field(default="", description="提示说明")
    comparison_note: str = Field(default="", description="对比说明")

class CostAnalysisUpdateRequest(BaseModel):
    items: List[CostItemUpdateRequest] = Field(..., description="BOM成本分项列表")
    analysis_summary: Optional[str] = Field(default="", description="成本核算总结")

@router.put("/{document_id}/cost-analysis", response_model=ResponseModel[dict])
async def update_cost_analysis(
    document_id: str,
    payload: CostAnalysisUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_user)
):
    """
    手动更新/保存 BOM 成本核算明细与自定义费用分项。
    同时重新汇总预估总成本、联动更新预算状态，并同步落盘至 CostEstimate 数据库实体表。
    """
    from sqlalchemy.orm.attributes import flag_modified
    from app.db.crud.document import document_crud
    from app.db.models.ai_analysis import CostEstimate
    import re

    # 1. 鉴权验证：确保文档属于当前用户
    doc = document_crud.get_document_by_id(db, document_id, current_user.id, current_user.tenant_id)
    if not doc:
        raise HTTPException(status_code=403, detail="无权访问该文档或文档不存在")

    # 2. 重新计算小计与预估总成本
    calculated_items = []
    total_cost = 0.0
    unmatched_count = 0

    for item in payload.items:
        item_dict = item.model_dump()
        raw_qty = item_dict.get("qty")
        ref_price = float(item_dict.get("ref_price") or 0.0)
        
        try:
            qty = float(raw_qty) if raw_qty is not None else 1.0
        except (ValueError, TypeError):
            qty = 1.0
            item_dict["qty"] = 1.0

        subtotal = round(qty * ref_price, 2)
        item_dict["subtotal"] = subtotal
        
        if ref_price <= 0:
            unmatched_count += 1
            if not item_dict.get("match_quality"):
                item_dict["match_quality"] = "未匹配"

        total_cost += subtotal
        calculated_items.append(item_dict)

    total_cost = round(total_cost, 2)

    # 3. 评估预算状态
    parsed_metadata = dict(doc.parsed_metadata or {})
    budget_limit = parsed_metadata.get("budget_limit")
    budget_status = "预算未设置"
    budget_numeric = None

    if budget_limit:
        try:
            cleaned_budget = re.sub(r'[^\d.]', '', str(budget_limit))
            if cleaned_budget:
                budget_numeric = float(cleaned_budget)
        except Exception as e:
            logger.warning(f"解析预算数字失败: {budget_limit}, error: {e}")

    if budget_numeric and budget_numeric > 0:
        ratio = round((total_cost / budget_numeric) * 100, 1)
        if total_cost > budget_numeric:
            budget_status = f"已超出预算上限 (预算使用率 {ratio}%, 超额 ¥{round(total_cost - budget_numeric, 2)})"
        elif ratio >= 90:
            budget_status = f"接近预算上限 (预算使用率 {ratio}%)"
        else:
            budget_status = f"预算可控 (预算使用率 {ratio}%)"

    cost_data = {
        "items": calculated_items,
        "total_cost": total_cost,
        "unmatched_count": unmatched_count,
        "budget_limit": budget_limit,
        "budget_status": budget_status,
        "analysis_summary": payload.analysis_summary or (parsed_metadata.get("cost_analysis") or {}).get("analysis_summary", "已完成手动调整与成本核算汇总。")
    }

    # 4. 持久化至 parsed_metadata JSONB
    parsed_metadata["cost_analysis"] = cost_data
    doc.parsed_metadata = parsed_metadata
    flag_modified(doc, "parsed_metadata")

    # 5. 同步落盘至 CostEstimate 实体数据表
    try:
        from app.db.models.project import Project
        valid_project_id = doc.project_id
        if valid_project_id:
            proj_exists = db.query(Project).filter(Project.id == valid_project_id).first()
            if not proj_exists:
                valid_project_id = None

        db.query(CostEstimate).filter(CostEstimate.document_id == document_id).delete()
        for item in calculated_items:
            est = CostEstimate(
                tenant_id=current_user.tenant_id,
                document_id=document_id,
                project_id=valid_project_id,
                item_name=item.get("name", "未命名项"),
                quantity=float(item.get("qty") or 1.0),
                unit=item.get("unit", "项"),
                unit_price=float(item.get("ref_price") or 0.0),
                calculated_total=float(item.get("subtotal") or 0.0),
                brand=item.get("brand_requirements", "") or item.get("matched_brand", ""),
                spec=item.get("spec_requirement", "") or item.get("matched_model", ""),
                remark=item.get("comparison_note", "") or item.get("warning", "") or "手动新增/调整项目"
            )
            db.add(est)
        db.commit()
        logger.info(f"成功更新文档 {document_id} 的 BOM 成本测算，共 {len(calculated_items)} 项，总额: ¥{total_cost}")
    except Exception as db_err:
        logger.exception(f"更新 CostEstimate 实体表异常: {db_err}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"数据落盘失败: {str(db_err)}")

    return success_response(data=cost_data, message="BOM 成本测算数据保存成功")

@router.get("/draft/download/{document_id}")

async def download_bidding_draft(
    document_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_user)
):
    """
    下载 AI 生成的投标书 Word 草稿 (.docx)
    """
    from app.db.crud.document import document_crud
    doc = document_crud.get_document_by_id(db, document_id, current_user.id, current_user.tenant_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在或无权访问")
        
    parsed_meta = doc.parsed_metadata or {}
    draft_path = parsed_meta.get("draft_path")
    expected_path = f"uploads/drafts/draft_{document_id}.docx"
    
    # 智能缓存检查：若草稿文件已存在，直接秒级返回 FileResponse
    target_file_path = draft_path if (draft_path and os.path.exists(draft_path)) else (expected_path if os.path.exists(expected_path) else None)
    
    if not target_file_path:
        logger.info(f"磁盘未搜寻到草稿，触发在线动态生成草稿，文档ID: {document_id}")
        try:
            from app.agents.bid_filler_agent import bid_filler_orchestrator_node as writer_agent_node
            state = {
                "document_id": document_id,
                "user_id": current_user.id,
                "tenant_id": current_user.tenant_id,
                "company_quals": parsed_meta.get("company_quals", "")
            }
            writer_res = writer_agent_node(state)
            target_file_path = writer_res.get("draft_path")
            if not target_file_path or not os.path.exists(target_file_path):
                raise HTTPException(status_code=404, detail="投标书草稿生成失败")
        except Exception as gen_err:
            logger.exception(f"动态生成草稿失败: {gen_err}")
            raise HTTPException(status_code=500, detail=f"投标书草稿实时生成失败: {str(gen_err)}")
    else:
        logger.info(f"秒级命中磁盘缓存草稿，直接返回文件: {target_file_path}")
            
    clean_filename = doc.filename.rsplit('.', 1)[0]
    filename = f"投标书草稿_{clean_filename}.docx"
    
    return FileResponse(
        path=draft_path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        content_disposition_type="attachment"
    )

@router.get("/opening-summary/download/{document_id}")
async def download_opening_summary(
    document_id: str,
    force: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_user)
):
    """
    实时触发 OpeningSummaryAgent 编写并下载最新版《开标一览表》Word 文档 (.docx)
    """
    from app.db.crud.document import document_crud
    doc = document_crud.get_document_by_id(db, document_id, current_user.id, current_user.tenant_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在或无权访问")
        
    logger.info(f"⚡ 点击导出开标一览表，实时调度 OpeningSummaryAgent 生成最新文件，文档ID: {document_id}")
    try:
        import importlib
        import app.agents.nodes.opening_summary_agent as osa_mod
        importlib.reload(osa_mod)
        
        state = {
            "document_id": document_id,
            "user_id": current_user.id,
            "tenant_id": current_user.tenant_id
        }
        summary_res = osa_mod.generate_opening_summary_node(state)
        target_file_path = summary_res.get("opening_summary_path")
        if not target_file_path or not os.path.exists(target_file_path):
            raise HTTPException(status_code=404, detail="开标一览表实时起草失败")
    except Exception as gen_err:
        logger.exception(f"实时起草开标一览表失败: {gen_err}")
        raise HTTPException(status_code=500, detail=f"开标一览表实时生成失败: {str(gen_err)}")
            
    clean_filename = doc.filename.rsplit('.', 1)[0]
    timestamp_str = datetime.now().strftime('%H%M%S')
    filename = f"开标一览表_{clean_filename}_{timestamp_str}.docx"
    
    return FileResponse(
        path=target_file_path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        content_disposition_type="attachment"
    )

@router.api_route("/download/{task_id}", methods=["GET", "HEAD"])
async def download_original_file(
    task_id: str, 
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(deps.get_current_user_optional)
):
    """
    根据 task_id 或 document_id 下载原文件（支持浏览器 PDF.js / SmartDocViewer 内嵌预览）
    """
    user_id = current_user.id if current_user else None
    tenant_id = current_user.tenant_id if current_user else None

    # 1. 首先尝试按照 document_id 查找 (用于历史记录与上传的标书)
    from app.db.crud.document import document_crud
    doc = None
    if user_id and tenant_id:
        doc = document_crud.get_document_by_id(db, task_id, user_id, tenant_id)
    if not doc:
        doc = document_crud.get_document_by_id_system(db, task_id)

    def _get_preview_file_and_name(fpath: str, fname: str) -> tuple[str, str]:
        """对于旧版 .doc 格式，优先交付已转换好的 .docx 文件，以便前端 docx-preview 本地渲染引擎精准呈现"""
        if fpath.lower().endswith(".doc"):
            docx_path = fpath + "x"
            if os.path.exists(docx_path):
                docx_name = (fname[:-4] if fname.lower().endswith(".doc") else fname) + ".docx"
                return docx_path, docx_name
            else:
                try:
                    from app.services.extractor_service import ExtractorService
                    docx_path = ExtractorService().convert_doc_to_docx(fpath)
                    if os.path.exists(docx_path):
                        docx_name = (fname[:-4] if fname.lower().endswith(".doc") else fname) + ".docx"
                        return docx_path, docx_name
                except Exception as e:
                    logger.warning(f"在线预览 .doc 转 .docx 抛出异常: {str(e)}")
        return fpath, fname

    if doc and doc.file_path and os.path.exists(doc.file_path):
        target_path, target_filename = _get_preview_file_and_name(doc.file_path, doc.filename)
        return FileResponse(
            path=target_path, 
            filename=target_filename,
            content_disposition_type="inline"
        )
    
    # 2. 查找匹配 task_id 的临时上传文件
    base_dir = Path(__file__).resolve().parent.parent.parent.parent
    upload_dir = os.path.join(base_dir, "uploads")
    pattern = os.path.join(upload_dir, f"{task_id}_*")
    matched_files = glob.glob(pattern)
    if matched_files and os.path.exists(matched_files[0]):
        file_path = matched_files[0]
        filename = os.path.basename(file_path).replace(f"{task_id}_", "")
        target_path, target_filename = _get_preview_file_and_name(file_path, filename)
        return FileResponse(
            path=target_path, 
            filename=target_filename,
            content_disposition_type="inline"
        )

    # 3. 查找 storage/temp_uploads 目录下的临时标书文件
    temp_dir = os.path.join("storage", "temp_uploads")
    if os.path.exists(temp_dir):
        for fname in os.listdir(temp_dir):
            if task_id in fname or (doc and doc.filename and doc.filename in fname):
                fpath = os.path.join(temp_dir, fname)
                orig_name = doc.filename if doc else fname
                target_path, target_filename = _get_preview_file_and_name(fpath, orig_name)
                return FileResponse(
                    path=target_path,
                    filename=target_filename,
                    content_disposition_type="inline"
                )

    raise HTTPException(status_code=404, detail="未找到对应的原文件")

