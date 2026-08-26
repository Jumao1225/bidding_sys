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
from app.utils.table_utils import normalize_section_name

router = APIRouter()

from app.db.models.user import User
from app.api import deps


def _find_task_upload_file(upload_dir: Path, task_id: str) -> Optional[str]:
    """在上传根目录及其业务子目录中定位指定任务保存的原文件。"""
    pattern = str(upload_dir / "**" / f"{task_id}_*")
    matched_files = sorted(glob.glob(pattern, recursive=True))
    return next((path for path in matched_files if os.path.isfile(path)), None)

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
        
        # 保存文件到招标文件专属目录 (uploads/tenders)
        base_dir = Path(__file__).resolve().parent.parent.parent.parent
        upload_dir = os.path.join(base_dir, "uploads", "tenders")
        os.makedirs(upload_dir, exist_ok=True)
        file_path = os.path.join(upload_dir, f"{task_id}_{file.filename}")
        
        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(status_code=400, detail="文件内容为空")
            
        with open(file_path, "wb") as f:
            f.write(file_bytes)
            
        logger.info(f"文件已保存: {file_path}，即将触发 Celery 任务: {task_id}")
        
        # 触发后台异步独立线程任务（绑定 ContextVar 确保 emit_agent_log 能正常将进度推送到 Redis 频道）
        import threading
        def _run_analyze_thread_with_context(t_id, f_path, f_name, c_quals, u_id, ten_id):
            from app.core.context import current_task_id
            token = current_task_id.set(t_id)
            try:
                analyze_bidding_doc(t_id, f_path, f_name, c_quals, u_id, ten_id)
            finally:
                try:
                    current_task_id.reset(token)
                except Exception:
                    pass

        parse_thread = threading.Thread(
            target=_run_analyze_thread_with_context,
            args=(task_id, file_path, file.filename, company_quals, current_user.id, current_user.tenant_id),
            daemon=True
        )
        parse_thread.start()
        
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
        
        from fastapi.concurrency import run_in_threadpool

        try:
            if domain in ("opening_summary", "opening_summary_agent"):
                from app.agents.nodes.opening_summary_agent import generate_opening_summary_node
                state = {
                    "document_id": document_id,
                    "user_id": current_user.id,
                    "tenant_id": current_user.tenant_id
                }
                summary_res = await run_in_threadpool(generate_opening_summary_node, state)
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
                cost_result = await run_in_threadpool(cost_node, state)
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
                qual_result = await run_in_threadpool(analyze_qualifications_node, state)
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
                writer_result = await run_in_threadpool(writer_agent_node, state)
                
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
            # 调用工具提取（异步线程池避让主事件循环）
            res_str = await run_in_threadpool(tool_func.invoke, {"document_id": document_id})
            
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

from pydantic import BaseModel, Field, field_validator


def _normalize_cost_text(value: Any) -> Any:
    """将历史结构化字段转换为接口可接受的文本，兼容旧版 {type, input} 数据。"""
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        for key in ("input", "text", "value", "content"):
            if key in value:
                nested_value = _normalize_cost_text(value[key])
                if nested_value:
                    return nested_value
        return str(value)
    return str(value)

class CostItemUpdateRequest(BaseModel):
    item_code: Optional[str] = Field(default=None, description="表格多级序号编码")
    name: str = Field(..., description="项目/设备名称")
    spec_requirement: str = Field(default="", description="规格或说明")
    qty: Optional[float] = Field(default=1.0, description="数量")
    unit: Optional[str] = Field(default="项", description="单位")
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
    remark: str = Field(default="", description="BOM 清单备注，与投标配置及分项报价表备注列对齐")
    parent_item: Optional[str] = Field(default=None, description="所属直接父级设备名称")
    root_item: Optional[str] = Field(default=None, description="所属顶层主要标的物名称")
    tree_level: Optional[int] = Field(default=1, description="层级深度（1=顶层主要标的物, 2=二级成套分项, 3=三级元器件）")
    per_set_qty: Optional[Any] = Field(default=None, description="单套设备定额数量")
    per_set_quantity: Optional[Any] = Field(default=None, description="单套设备定额数量别名")
    brand: Optional[str] = Field(default=None, description="品牌")
    model: Optional[str] = Field(default=None, description="规格型号")
    manufacturer: Optional[str] = Field(default=None, description="生产厂商")
    section_name: Optional[str] = Field(default=None, description="所属分标段/分区域/分项工程名称")

    @field_validator(
        "item_code", "name", "spec_requirement", "unit", "matched_name",
        "matched_brand", "matched_model", "matched_manufacturer",
        "brand_requirements", "match_quality", "warning", "comparison_note",
        "remark", "parent_item", "root_item", "brand", "model", "manufacturer",
        "section_name", mode="before"
    )
    @classmethod
    def normalize_text_fields(cls, value: Any) -> Any:
        """兼容历史解析结果中的结构化文本，避免单个异常字段导致整单 422。"""
        return _normalize_cost_text(value)

    @field_validator("key_parameters", mode="before")
    @classmethod
    def normalize_key_parameters(cls, value: Any) -> List[str]:
        """将关键参数统一为字符串列表，保证前端展示和后续持久化稳定。"""
        if value is None:
            return []
        values = value if isinstance(value, list) else [value]
        return [text for item in values if (text := _normalize_cost_text(item))]

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

    # 构建设备所属成套关系与区域属性参考字典（从工程元数据与历史记录中自动继承）
    parent_map = {}
    from app.db.models.metadata import EngineeringMetadata
    eng_md = db.query(EngineeringMetadata).filter(EngineeringMetadata.document_id == document_id).first()
    eng_list = getattr(eng_md, "main_equipment_list", None) if eng_md else None
    if eng_list and isinstance(eng_list, list):
        for eq in eng_list:
            if isinstance(eq, dict) and eq.get("item_name"):
                nm = eq["item_name"].strip()
                parent_map[nm] = {
                    "item_code": eq.get("item_code"),
                    "parent_item": eq.get("parent_item"),
                    "root_item": eq.get("root_item"),
                    "tree_level": eq.get("tree_level"),
                    "per_set_qty": eq.get("per_set_quantity") or eq.get("per_set_qty"),
                    "section_name": eq.get("section_name")
                }

    # 2. 补齐属性并执行自底向上树形层级汇总（防双重计费并计算成套母项小计与折合单价）
    from app.services.cost_service import rollup_hierarchical_cost_items
    raw_item_list = []

    def _optional_float(value):
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    for item in payload.items:
        item_dict = item.model_dump()
        raw_qty = item_dict.get("qty")
        ref_price = float(item_dict.get("ref_price") or 0.0)
        
        # 自动补齐 parent_item、per_set_qty 与 section_name、item_code 等（如果 payload 中缺失）
        name_key = (item_dict.get("name") or "").strip()
        if name_key in parent_map:
            if not item_dict.get("item_code") and parent_map[name_key].get("item_code"):
                item_dict["item_code"] = parent_map[name_key]["item_code"]
            if not item_dict.get("parent_item") and parent_map[name_key].get("parent_item"):
                item_dict["parent_item"] = parent_map[name_key]["parent_item"]
            if not item_dict.get("root_item") and parent_map[name_key].get("root_item"):
                item_dict["root_item"] = parent_map[name_key]["root_item"]
            if not item_dict.get("tree_level") and parent_map[name_key].get("tree_level"):
                item_dict["tree_level"] = parent_map[name_key]["tree_level"]
            if not item_dict.get("per_set_qty") and parent_map[name_key].get("per_set_qty"):
                item_dict["per_set_qty"] = parent_map[name_key]["per_set_qty"]
            if not item_dict.get("section_name") and parent_map[name_key].get("section_name"):
                item_dict["section_name"] = parent_map[name_key]["section_name"]

        try:
            qty = float(raw_qty) if raw_qty is not None else 1.0
        except (ValueError, TypeError):
            qty = 1.0
            item_dict["qty"] = 1.0

        # 兼容品牌、型号与厂商的多别名映射
        if item_dict.get("brand") and not item_dict.get("matched_brand"):
            item_dict["matched_brand"] = item_dict["brand"]
        elif item_dict.get("matched_brand") and not item_dict.get("brand"):
            item_dict["brand"] = item_dict["matched_brand"]
            
        if item_dict.get("model") and not item_dict.get("matched_model"):
            item_dict["matched_model"] = item_dict["model"]
        elif item_dict.get("matched_model") and not item_dict.get("model"):
            item_dict["model"] = item_dict["matched_model"]

        if item_dict.get("manufacturer") and not item_dict.get("matched_manufacturer"):
            item_dict["matched_manufacturer"] = item_dict["manufacturer"]
        elif item_dict.get("matched_manufacturer") and not item_dict.get("manufacturer"):
            item_dict["manufacturer"] = item_dict["matched_manufacturer"]

        item_dict["ref_price"] = ref_price
        raw_item_list.append(item_dict)

    calculated_items, total_cost, unmatched_count = rollup_hierarchical_cost_items(raw_item_list)

    # 3. 评估预算与最高限价状态（严格优先级：最高投标限价 max_price_limit > 采购总预算 budget > parsed_metadata 兜底）
    from app.db.models.metadata import FinancialMetadata
    parsed_metadata = dict(doc.parsed_metadata or {})
    
    fin_md = db.query(FinancialMetadata).filter(FinancialMetadata.document_id == document_id).first()
    
    budget_status = "预算未设置"
    budget_numeric = None
    budget_limit_str = None
    limit_type = "unspecified"

    if fin_md:
        if fin_md.max_price_limit and isinstance(fin_md.max_price_limit, dict) and fin_md.max_price_limit.get("amount"):
            try:
                budget_numeric = float(fin_md.max_price_limit["amount"])
                budget_limit_str = f"最高投标限价 ¥{budget_numeric:,.2f}"
                limit_type = "max_price_limit"
            except (ValueError, TypeError) as e:
                logger.warning(f"解析最高投标限价数字失败: {fin_md.max_price_limit}, error: {e}")
        elif fin_md.budget and isinstance(fin_md.budget, dict) and fin_md.budget.get("amount"):
            try:
                budget_numeric = float(fin_md.budget["amount"])
                budget_limit_str = f"采购总预算 ¥{budget_numeric:,.2f}"
                limit_type = "budget"
            except (ValueError, TypeError) as e:
                logger.warning(f"解析采购总预算数字失败: {fin_md.budget}, error: {e}")

    # 兜底旧逻辑：从 parsed_metadata 读取 budget_limit
    if budget_numeric is None:
        raw_budget_limit = parsed_metadata.get("budget_limit") or (parsed_metadata.get("cost_analysis") or {}).get("budget_limit")
        if raw_budget_limit:
            try:
                cleaned_budget = re.sub(r'[^\d.]', '', str(raw_budget_limit))
                if cleaned_budget:
                    budget_numeric = float(cleaned_budget)
                    budget_limit_str = str(raw_budget_limit)
                    limit_type = "budget_limit"
            except Exception as e:
                logger.warning(f"解析预算数字失败: {raw_budget_limit}, error: {e}")

    if budget_numeric and budget_numeric > 0:
        ratio = round((total_cost / budget_numeric) * 100, 1)
        overrun_amt = round(total_cost - budget_numeric, 2)
        limit_name = "最高投标限价" if limit_type == "max_price_limit" else ("采购总预算" if limit_type == "budget" else "预算上限")
        if total_cost > budget_numeric:
            budget_status = f"已超出{limit_name} (使用率 {ratio}%, 超额 ¥{overrun_amt:,.2f})"
        elif ratio >= 90:
            budget_status = f"接近{limit_name} (使用率 {ratio}%)"
        else:
            budget_status = f"在{limit_name}内可控 (使用率 {ratio}%)"

    cost_data = {
        "items": calculated_items,
        "total_cost": total_cost,
        "unmatched_count": unmatched_count,
        "budget_limit": budget_limit_str,
        "budget_numeric": budget_numeric,
        "limit_type": limit_type,
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
        for sort_order, item in enumerate(calculated_items):
            # 提取品牌、型号与生产厂商（仅采用对标匹配或用户填写的品牌、型号与厂家，无则直接留空，严禁回退采用标书要求文字）
            effective_brand = str(item.get("matched_brand") or item.get("brand") or "").strip()
            effective_model = str(item.get("matched_model") or item.get("model") or "").strip()
            effective_mfg = str(item.get("matched_manufacturer") or item.get("manufacturer") or "").strip()

            est = CostEstimate(
                tenant_id=current_user.tenant_id,
                user_id=current_user.id,
                document_id=document_id,
                project_id=valid_project_id,
                item_code=str(item.get("item_code") or "").strip() or None,
                item_name=str(item.get("name") or "未命名项"),
                quantity=float(item.get("qty") or 1.0),
                unit=str(item.get("unit")) if item.get("unit") is not None else None,
                unit_price=float(item.get("ref_price") or 0.0),
                calculated_total=float(item.get("subtotal") or 0.0),
                brand=effective_brand or None,
                model=effective_model or None,
                manufacturer=effective_mfg or None,
                spec=effective_model or None,
                spec_requirement=str(item.get("spec_requirement") or "").strip() or None,
                matched_name=str(item.get("matched_name") or "").strip() or None,
                matched_brand=str(item.get("matched_brand") or "").strip() or None,
                matched_model=str(item.get("matched_model") or "").strip() or None,
                matched_manufacturer=str(item.get("matched_manufacturer") or "").strip() or None,
                key_parameters=item.get("key_parameters") or [],
                brand_requirements=str(item.get("brand_requirements") or "").strip() or None,
                match_quality=str(item.get("match_quality") or "").strip() or None,
                warning=str(item.get("warning") or "").strip() or None,
                comparison_note=str(item.get("comparison_note") or "").strip() or None,
                parent_item=str(item.get("parent_item") or "").strip() or None,
                root_item=str(item.get("root_item") or "").strip() or None,
                tree_level=int(item.get("tree_level")) if item.get("tree_level") is not None else None,
                per_set_qty=_optional_float(item.get("per_set_qty")),
                per_set_quantity=_optional_float(item.get("per_set_quantity")),
                section_name=normalize_section_name(item.get("section_name")),
                remark=str(item.get("remark") or "").strip() or None,
                sort_order=sort_order,
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
        logger.info(f"未在磁盘搜寻到现成草稿，提示用户手动点击起草，文档ID: {document_id}")
        raise HTTPException(status_code=404, detail="投标书草稿尚未生成，请在页面中点击【生成/起草标书】按钮手动触发。")
    clean_filename = doc.filename.rsplit('.', 1)[0]
    filename = f"投标书草稿_{clean_filename}.docx"
    
    return FileResponse(
        path=target_file_path or draft_path,
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
    
    # 2. 查找匹配 task_id 的上传文件，兼容 uploads/tenders 等业务子目录
    base_dir = Path(__file__).resolve().parent.parent.parent.parent
    upload_dir = base_dir / "uploads"
    file_path = _find_task_upload_file(upload_dir, task_id)
    if file_path:
        filename = os.path.basename(file_path).removeprefix(f"{task_id}_")
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

    logger.warning("原文件预览未找到文件: task_or_document_id={}", task_id)
    raise HTTPException(status_code=404, detail="未找到对应的原文件")
