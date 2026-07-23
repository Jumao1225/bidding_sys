import json
from loguru import logger
from app.services.llm_service import llm_service
from app.agents.state import BiddingState
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.db.crud.document import document_crud
from app.db.crud.business import business_crud
from app.core.audit_decorator import audit_node
from app.services.rag_service import rag_service
from pydantic import BaseModel, Field
from typing import List, Optional

class CostItem(BaseModel):
    name: str = Field(description="采购清单中原始的物品/设备名称")
    spec_requirement: str = Field(default="", description="招标文件中要求的规格参数与技术要求（必须尽量原汁原味摘录标书原文，严禁总结简化）")
    qty: float = Field(default=1.0, description="采购数量")
    unit: str = Field(default="台", description="单位")
    key_parameters: List[str] = Field(default_factory=list, description="关键星号(*)技术指标参数明细")
    brand_requirements: str = Field(default="", description="招标文件要求的品牌或产地要求")
    matched_name: str = Field(default="", description="价格参考库中匹配到的设备名称")
    matched_brand: str = Field(default="", description="匹配到的品牌")
    matched_model: str = Field(default="", description="匹配到的规格/型号")
    matched_manufacturer: str = Field(default="", description="匹配到的生产厂商")
    ref_price: float = Field(default=0.0, description="匹配到的参考指导单价（未匹配时强制为 0）")
    subtotal: float = Field(default=0.0, description="成本小计金额 (qty * ref_price)")
    match_quality: str = Field(default="未匹配", description="匹配置信度: 精准匹配 | 模糊匹配 | 未匹配")
    warning: str = Field(default="", description="提示或警告说明")
    comparison_note: str = Field(default="", description="标书原文规格要求与价格库匹配到的自有设备规格参数的详细对比分析")

class CostAnalysisResult(BaseModel):
    items: List[CostItem] = Field(description="核算出的所有物品清单", default_factory=list)
    analysis_summary: str = Field(default="", description="成本核算专家总结与风险评估说明")

@audit_node(name="CostAgent-CalculateCost")
def cost_node(state: BiddingState) -> dict:
    """
    智能成本测算节点（CostAgent）。
    使用 RAG 靶向检索招标文件的采购清单与已提取工程设备明细，
    并与包含品牌、规格、型号、生产厂商的全维度企业价格库进行智能语义匹配与成本核算。
    """
    from app.worker.tasks import emit_agent_log
    document_id = state.get("document_id")
    user_id = state.get("user_id")
    tenant_id = state.get("tenant_id") or "default-tenant"
    
    emit_agent_log("info", "启动成本核算专家...", extra={"type": "worker_start", "worker": "cost_estimation"})
    
    db: Session = SessionLocal()
    budget_limit = None
    price_book = []
    equipment_list_from_db = []
    
    try:
        document = document_crud.get_document_by_id(db, document_id, user_id, tenant_id)
        if document and document.parsed_metadata:
            budget_limit = document.parsed_metadata.get("budget_limit")
            
        # 获取当前租户的全维度价格参考库
        price_refs = business_crud.get_all_price_references(db, tenant_id)
        price_book = [
            {
                "item_name": ref.item_name,
                "brand": ref.brand or "",
                "spec": ref.spec or "",
                "model": ref.model or "",
                "manufacturer": ref.manufacturer or "",
                "unit_price": ref.unit_price,
                "unit": ref.unit or "台",
                "remark": ref.remark or ""
            }
            for ref in price_refs
        ]

        # 获取工程元数据中已经提取的设备明细清单（若有）
        from app.db.models.metadata import EngineeringMetadata
        eng_meta = db.query(EngineeringMetadata).filter(
            EngineeringMetadata.document_id == document_id,
            EngineeringMetadata.tenant_id == tenant_id
        ).first()
        if eng_meta and eng_meta.main_equipment_list:
            raw_list = eng_meta.main_equipment_list
            if isinstance(raw_list, list):
                equipment_list_from_db = [
                    item if isinstance(item, dict) else (item.model_dump() if hasattr(item, "model_dump") else item)
                    for item in raw_list
                ]
    except Exception as e:
        logger.warning(f"CostAgent 数据库数据读取出现异常: {e}")
    finally:
        db.close()

    # 使用 RAG 靶向检索采购清单、货物需求一览表、技术规格书与详细参数
    rag_text = rag_service.search_bidding_document(
        document_id, 
        "采购清单 货物需求一览表 设备清单 BOM 报价 技术规格书 材质尺寸 参数要求 项目需求", 
        top_k=10, 
        disable_expansion=True
    )
    
    logger.info(f"开始成本核算节点，靶向检索文本长度: {len(rag_text)}，已提取工程设备项数: {len(equipment_list_from_db)}，参考价格库项数: {len(price_book)}。")

    prompt = f"""
    你是一位资深的工程与设备成本核算专家。
    请分析以下招标文件中提取的【主控标准设备需求清单】与【招标片段原文】，对采购设备进行成本核算，
    并将其与企业内部【全维度价格参考库（即自有设备库）】进行智能通用语义匹配、备注参考与参数对比。

    【主控提取的标准设备需求清单 (最高优先基准)】:
    {json.dumps(equipment_list_from_db, ensure_ascii=False, indent=2) if equipment_list_from_db else "暂无预先提取清单"}

    【招标片段原文参考】:
    {rag_text}

    【企业全维度价格参考库（自有设备库）】:
    {json.dumps(price_book, ensure_ascii=False, indent=2)}

    【智能匹配、参数对比与防重复计价规则】:
    1. 【标准 BOM 忠实继承与原始名称强保持（最高指令）】：
       - 若存在【主控提取的标准设备需求清单】，你**必须 100% 完整保留**清单中的所有设备项目！
       - **绝对禁止修改设备原始名称(name)，绝对禁止擅自添加任何自定义后缀、符号或编号！**
       - 原始名称(name)必须与【主控提取的标准设备需求清单】中的名称 100% 完全一致！
       - 规格参数要求(spec_requirement/specifications) **必须原汁原味地保留标书原文中的参数描述，严禁归纳简化**！
       - **摒弃“详见XXX”空话 (重要)**：若继承的规格里写有“详见技术规格”、“详见项目需求”或只包含控制价文本，你**必须从【招标片段原文参考】中搜寻并替换为该设备真实的材质、尺寸、物理/电气等详细技术参数描述**！
       - 保留其原始采购数量(qty)、单位(unit)、品牌要求(brand_requirements)及关键星号参数(key_parameters)。
    2. 【参考价格库备注 (remark) 识别与打包统价防重复计算规则（重要）】：
       - 你**必须仔细阅读价格参考库中各条目的 `remark` 备注说明**！
       - 如果价格库某设备的 `remark` 中指明该价格为打包价、统价或包含多种规格的说明：
         - 当标书清单中拆分出了多个属于该打包范围的分项规格时，**只允许在第一个对应匹配项中赋予参考单价 `ref_price`**；
         - **对于已被上一项或打包项覆盖的后续规格/分项，其 `ref_price` 必须强制设为 0.0**！
         - 在 `comparison_note` 中明确标注分析结论：说明该规格已包含在打包计价项目中，不重复计算成本。
    3. 【物理数量与计价单位智能对齐规则 (严防漏算/少算数量)】：
       - 当价格库参考设备的指导单价为单件/单台价格，而标书清单单位被填为了汇总打包单位时：
       - 你必须核对标书原文规格描述中明确提到的具体物理数量总和。
       - **你必须将 `qty` 修正设为实际物理数量的总和，并将 `unit` 调整设为单价对应的物理计价单位**！
       - 绝对禁止在单价为单件价格时误将 `qty` 留为 1 导致最终总成本少算！
    4. 【自有设备对比分析 (comparison_note)】：
       - 请将【标书原文规格要求】与匹配到的【自有设备（价格库设备）的品牌/规格型号/厂商/备注】进行详细的参数与对标分析。
       - 在 `comparison_note` 字段中写明具体的对比分析结论（指明标书参数与自有设备参数的对比关系及计价说明）。
    5. 【智能语义同义词与大类设备通用匹配】：
       请将标准 BOM 项目与“企业全维度价格参考库”中的设备进行通用语义比对：
       - 若采购物品为抽象大类或同等功能替代物，必须识别并填充 matched_name, matched_brand, matched_model, matched_manufacturer，并参考其指导单价！
    6. 【置信度划分】：
       - 若名称、品牌或规格型号高度吻合，match_quality 标为 "精准匹配"；
       - 若属于同类设备或同等替代物，match_quality 标为 "模糊匹配"；
       - 若价格库中完全没有任何同类或相关设备，ref_price 强制设为 0，matched_name 留空，match_quality 标为 "未匹配"，warning 填 "未在价格库中找到参考价"。
    7. 自动计算每项小计 subtotal = qty * ref_price。
    8. 在 analysis_summary 中给出整体成本测算总结。
    """

    logger.debug("正在调用 LLM 进行智能 BOM 提取和全维度价格匹配...")
    response_obj: CostAnalysisResult = llm_service.generate_structured_output(
        prompt=prompt,
        schema_cls=CostAnalysisResult,
        temperature=0.0
    )
    
    calculated_items = []
    total_cost = 0.0
    unmatched_count = 0
    
    for idx, item in enumerate(response_obj.items):
        item_dict = item.model_dump()
        
        # 强行保护与死锁还原：设备原始名称 100% 保持与数据库记录完全一致，防大模型篡改添加 -1/-2 后缀
        if equipment_list_from_db and idx < len(equipment_list_from_db):
            orig_item = equipment_list_from_db[idx]
            orig_name = orig_item.get("item_name") or orig_item.get("name")
            if orig_name:
                item_dict["name"] = orig_name

        raw_qty = item_dict.get("qty")
        ref_price = item_dict.get("ref_price", 0.0)
        
        # 兼容防护：若对标分析及备注明确标明已在上一项或打包项目中包含，确保单价不重复计算
        note = item_dict.get("comparison_note", "")
        if ("不重复" in note and "计算" in note) or ("合并" in note and "计价" in note) or ("已包含" in note and "统价" in note):
            ref_price = 0.0
            item_dict["ref_price"] = 0.0

        if raw_qty is not None:
            try:
                qty = float(raw_qty)
                subtotal = round(qty * ref_price, 2)
            except (ValueError, TypeError):
                item_dict["qty"] = None
                subtotal = 0.0
        else:
            item_dict["qty"] = None
            subtotal = 0.0

        item_dict["subtotal"] = subtotal
        
        if ref_price <= 0:
            unmatched_count += 1
            item_dict["match_quality"] = "未匹配"
            if not item_dict.get("warning"):
                item_dict["warning"] = "未在价格库中找到参考价"
                
        total_cost += subtotal
        calculated_items.append(item_dict)

    total_cost = round(total_cost, 2)
    
    # 预算对比与风险预警
    budget_status = "预算未设置"
    budget_numeric = None
    
    if budget_limit:
        try:
            import re
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

    logger.info(f"成本核算完成，总估算成本: {total_cost}，预算状态: {budget_status}，未匹配项: {unmatched_count}。")
    
    summary = f"完成 BOM 成本核算：包含 {len(calculated_items)} 项设备，预估总成本 ¥{total_cost:,.2f}"
    if unmatched_count > 0:
        summary += f"（{unmatched_count} 项未在库中找到参考价）"

    emit_agent_log("info", summary, extra={"type": "worker_complete", "worker": "cost_estimation", "status": "success", "summary": summary})
    
    return {
        "cost_analysis": {
            "total_cost": total_cost,
            "budget_limit": budget_limit,
            "budget_numeric": budget_numeric,
            "budget_status": budget_status,
            "unmatched_count": unmatched_count,
            "analysis_summary": response_obj.analysis_summary,
            "items": calculated_items
        },
        "completed_steps": ["cost_estimation"],
        "worker_summaries": [{
            "worker": "cost_estimation",
            "status": "success",
            "summary": summary
        }]
    }
