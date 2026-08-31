import json
import re
import unicodedata
from loguru import logger
from app.services.llm_service import llm_service
from app.agents.state import BiddingState
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.db.crud.document import document_crud
from app.db.crud.business import business_crud
from app.db.models.business import MarketPriceReference
from app.core.audit_decorator import audit_node
from app.agents.tools.rag_tools import search_bidding_document
from pydantic import BaseModel, Field
from typing import List, Optional

class ItemMatchOutput(BaseModel):
    item_index: int = Field(default=0, description="当前批次内设备的数字索引编号 (从 0 开始)")
    ref_price: Optional[float] = Field(default=0.0, description="匹配到的参考指导单价（未匹配或已包含在成套统价中时强制为 0.0）")
    matched_name: Optional[str] = Field(default="", description="价格参考库中匹配到的设备名称")
    matched_brand: Optional[str] = Field(default="", description="匹配到的品牌")
    matched_model: Optional[str] = Field(default="", description="匹配到的规格型号")
    matched_manufacturer: Optional[str] = Field(default="", description="匹配到的生产厂商")
    match_quality: Optional[str] = Field(default="未匹配", description="匹配置信度: 精准匹配 | 模糊匹配 | 未匹配")
    comparison_note: Optional[str] = Field(default="", description="标书参数与自有设备参数的详细对标分析及计价说明")
    warning: Optional[str] = Field(default="", description="未匹配或规格偏差的风险提示")
    # 可选兼容字段（用于无预提清单时的降级模式及单元测试 Mock）
    name: Optional[str] = None
    spec_requirement: Optional[str] = None
    qty: Optional[float] = None
    unit: Optional[str] = None
    subtotal: Optional[float] = None
    item_code: Optional[str] = None
    parent_item: Optional[str] = None
    root_item: Optional[str] = None
    tree_level: Optional[int] = None
    per_set_qty: Optional[float] = None
    section_name: Optional[str] = None
    key_parameters: Optional[List[str]] = None
    brand_requirements: Optional[str] = None

class BatchMatchResult(BaseModel):
    matches: List[ItemMatchOutput] = Field(description="当前批次各设备的对标结果列表", default_factory=list)
    batch_summary: Optional[str] = Field(default="", description="本批次设备对标核算小结")

class CostItem(BaseModel):
    item_code: Optional[str] = Field(default=None, description="表格多级序号编码（如 '(一)', '1', '1.1', '1.3' 等）")
    name: str = Field(description="采购清单中原始的物品/设备名称")
    spec_requirement: Optional[str] = Field(default="", description="招标文件中要求的规格参数与技术要求")
    qty: Optional[float] = Field(default=1.0, description="项目物理总采购需求量")
    unit: Optional[str] = Field(default=None, description="单位")
    parent_item: Optional[str] = Field(default=None, description="直接所属父级设备名称")
    root_item: Optional[str] = Field(default=None, description="所属顶层主要标的物名称")
    tree_level: Optional[int] = Field(default=1, description="层级深度：1=顶层主要标的物, 2=二级成套总成, 3=三级核心元器件, 4+=更细分子项")
    per_set_qty: Optional[float] = Field(default=None, description="单套定额数量")
    section_name: Optional[str] = Field(default=None, description="所属工程大类分部名称")
    key_parameters: Optional[List[str]] = Field(default_factory=list, description="关键星号(*)技术指标参数明细")
    brand_requirements: Optional[str] = Field(default="", description="要求的品牌或产地要求")
    matched_name: Optional[str] = Field(default="", description="价格参考库中匹配到的设备名称")
    matched_brand: Optional[str] = Field(default="", description="匹配到的品牌")
    matched_model: Optional[str] = Field(default="", description="匹配到的规格/型号")
    matched_manufacturer: Optional[str] = Field(default="", description="匹配到的生产厂商")
    ref_price: Optional[float] = Field(default=0.0, description="匹配到的参考指导单价")
    subtotal: Optional[float] = Field(default=0.0, description="成本小计金额 (qty * ref_price)")
    match_quality: Optional[str] = Field(default="未匹配", description="匹配置信度: 精准匹配 | 模糊匹配 | 未匹配")
    warning: Optional[str] = Field(default="", description="提示或警告说明")
    comparison_note: Optional[str] = Field(default="", description="对比分析及计价说明")
    remark: Optional[str] = Field(default="", description="匹配价格库中的 BOM 备注")


def resolve_price_reference_remark(match_info: object, price_book: list[dict]) -> str:
    """根据本地匹配结果回查价格库备注，避免由大模型臆造备注内容。"""
    if match_info is None or not price_book:
        return ""

    def normalize(value: object) -> str:
        return str(value or "").strip().casefold()

    matched_name = normalize(getattr(match_info, "matched_name", ""))
    if not matched_name:
        return ""

    matched_brand = normalize(getattr(match_info, "matched_brand", ""))
    matched_model = normalize(getattr(match_info, "matched_model", ""))
    matched_manufacturer = normalize(getattr(match_info, "matched_manufacturer", ""))
    matched_price = getattr(match_info, "ref_price", 0.0) or 0.0

    best_score = 0
    best_remark = ""
    for reference in price_book:
        reference_name = normalize(reference.get("item_name"))
        if reference_name == matched_name:
            score = 8
        elif matched_name in reference_name or reference_name in matched_name:
            score = 4
        else:
            continue

        if matched_brand and matched_brand == normalize(reference.get("brand")):
            score += 2
        if matched_model and matched_model == normalize(reference.get("model") or reference.get("spec")):
            score += 3
        if matched_manufacturer and matched_manufacturer == normalize(reference.get("manufacturer")):
            score += 2

        try:
            if abs(float(reference.get("unit_price") or 0.0) - float(matched_price)) < 0.0001:
                score += 2
        except (TypeError, ValueError):
            logger.warning(f"价格库单价格式异常，跳过备注匹配评分: {reference.get('unit_price')}")

        if score > best_score:
            best_score = score
            best_remark = str(reference.get("remark") or "").strip()

    return best_remark

class CostAnalysisResult(BaseModel):
    items: List[CostItem] = Field(description="核算出的所有物品清单", default_factory=list)
    analysis_summary: Optional[str] = Field(default="", description="成本核算专家总结与风险评估说明")


def _get_cost_rag_context(document_id: str, tenant_id: str) -> str:
    """调用现有通用 RAG 工具，为成本核算补充招标原文依据。"""
    if not document_id:
        return ""

    query = "采购清单 工程量清单 设备材料 规格型号 数量 单位 参考价格"
    try:
        context = search_bidding_document.invoke({
            "document_id": document_id,
            "query": query,
        })
        normalized_context = str(context or "").strip()
        logger.info(
            "CostAgent 已调用通用 RAG 工具补充成本核算原文：文档ID=%s，租户=%s，上下文字符数=%d",
            document_id,
            tenant_id,
            len(normalized_context),
        )
        return normalized_context
    except Exception as exc:
        logger.exception(
            "CostAgent 调用通用 RAG 工具失败，将仅依据工程元数据继续核算：文档ID=%s，错误=%s",
            document_id,
            exc,
        )
        return ""

def filter_candidate_price_book(batch_items: list, full_price_book: list, max_candidates: int = 50) -> list:
    """
    针对当前批次的设备列表，从全量海量价格库中智能动态筛选出最相关的候选价格条目。
    - 当价格库总数 <= max_candidates 时，全量保留，避免漏配；
    - 当价格库庞大时（数百至数万条），通过提取批次核心特征与分词/n-gram打分，精准召回 Top-K 候选物料，
      将 Prompt 尺寸始终限制在安全范围内，彻底消除大海捞针与 Token 浪费。
    """
    import re
    if not full_price_book or len(full_price_book) <= max_candidates:
        return full_price_book

    if not batch_items:
        return full_price_book[:max_candidates]

    # 1. 提取当前批次中所有设备的特征词集（名称、型号、规格、品牌）
    query_keywords = set()
    for item in batch_items:
        name = str(item.get("item_name") or item.get("name") or "")
        parent = str(item.get("parent_item") or "")
        spec = str(item.get("specifications") or item.get("spec") or "")
        brand = str(item.get("brand_requirements") or "")
        
        combined_text = f"{name} {parent} {spec} {brand}"
        # 提取英文/数字型号特征 (如 2000kVA, 10kV, YJV22, PHC400, Q235B 等)
        alphanum_tokens = re.findall(r'[a-zA-Z0-9_\-\./\+]+', combined_text)
        for tok in alphanum_tokens:
            if len(tok) >= 2:
                query_keywords.add(tok.lower())
                
        # 提取中文核心词
        chinese_chars = re.findall(r'[\u4e00-\u9fa5]+', combined_text)
        for chunk in chinese_chars:
            if len(chunk) <= 4:
                query_keywords.add(chunk)
            else:
                # 滑动窗口切词 2~3 字符
                for i in range(len(chunk) - 1):
                    query_keywords.add(chunk[i:i+2])
                    if i + 3 <= len(chunk):
                        query_keywords.add(chunk[i:i+3])

    # 2. 对价格库中每条记录进行相关度加权打分
    scored_items = []
    for p_item in full_price_book:
        score = 0.0
        p_name = str(p_item.get("item_name") or "").lower()
        p_model = str(p_item.get("model") or "").lower()
        p_spec = str(p_item.get("spec") or "").lower()
        p_brand = str(p_item.get("brand") or "").lower()
        p_cat = str(p_item.get("category") or "").lower()
        p_remark = str(p_item.get("remark") or "").lower()
        
        p_full = f"{p_name} {p_model} {p_spec} {p_brand} {p_cat} {p_remark}"
        
        for kw in query_keywords:
            if kw in p_name:
                score += 5.0  # 名称直接命中权重最高
            elif kw in p_model:
                score += 4.0  # 型号直接命中权重高
            elif kw in p_spec:
                score += 2.5  # 规格参数命中
            elif kw in p_brand:
                score += 2.0  # 品牌命中
            elif kw in p_cat:
                score += 1.5  # 品类命中
            elif kw in p_full:
                score += 0.5

        # 打包统价或通用系统条目保留适当的基础权重，防止成套打包项被漏掉
        if "成套" in p_name or "系统" in p_name or "包" in p_name or "综合" in p_name:
            score += 0.8

        scored_items.append((score, p_item))

    # 3. 按相关度降序排序并截取 Top-K
    scored_items.sort(key=lambda x: x[0], reverse=True)
    
    # 优先选取有相关得分的条目；若得分全为 0 则保留默认前部
    selected = [item for score, item in scored_items[:max_candidates]]
    return selected


def _normalize_price_match_text(value: object) -> str:
    """统一价格匹配文本，消除全半角、空格和常见标点差异。"""
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[\s,，、;；:：()（）\[\]【】/\\_\-]+", "", normalized)


def _longest_common_name_fragment(left: str, right: str) -> str:
    """获取两个名称的最长连续中文/数字片段，避免仅凭一个泛词误配。"""
    if not left or not right:
        return ""
    best = ""
    for start in range(len(left)):
        for end in range(start + 2, len(left) + 1):
            fragment = left[start:end]
            if len(fragment) > len(best) and fragment in right:
                best = fragment
    return best


def _is_count_unit(unit: object) -> bool:
    """判断单位是否属于可互换的离散件计数单位。"""
    return str(unit or "").strip() in {"台", "块", "个", "只", "组", "件"}


def _price_units_compatible(source_unit: object, reference_unit: object) -> bool:
    """判断清单单位与价格库单位是否允许直接计算价格。"""
    source = str(source_unit or "").strip()
    reference = str(reference_unit or "").strip()
    if not source or not reference:
        return True
    if source == reference:
        return True
    return _is_count_unit(source) and _is_count_unit(reference)


def find_local_price_reference(item: dict, price_book: list[dict]) -> Optional[dict]:
    """对明显同名/同类清单执行本地确定性匹配，作为模型结果的安全兜底。"""
    if not item or not price_book:
        return None

    source_name = _normalize_price_match_text(item.get("item_name") or item.get("name"))
    if not source_name:
        return None
    source_spec = _normalize_price_match_text(item.get("specifications") or item.get("spec_requirement"))
    source_unit = item.get("unit")
    ranked: list[tuple[int, dict, str]] = []

    for reference in price_book:
        reference_name = _normalize_price_match_text(reference.get("item_name"))
        if not reference_name:
            continue

        fragment = _longest_common_name_fragment(source_name, reference_name)
        if source_name == reference_name:
            name_score = 100
            quality = "精准匹配"
        elif source_name in reference_name or reference_name in source_name:
            name_score = 82
            quality = "模糊匹配"
        elif len(fragment) >= 4:
            name_score = 68 + min(len(fragment), 8)
            quality = "模糊匹配"
        else:
            continue

        score = name_score
        reference_spec = _normalize_price_match_text(reference.get("spec") or reference.get("model"))
        if source_spec and reference_spec:
            if source_spec == reference_spec:
                score += 20
            elif source_spec in reference_spec or reference_spec in source_spec:
                score += 10

        if _price_units_compatible(source_unit, reference.get("unit")):
            score += 12
        else:
            score -= 20
        ranked.append((score, reference, quality))

    if not ranked:
        return None
    ranked.sort(key=lambda value: value[0], reverse=True)
    score, reference, quality = ranked[0]
    if score < 60:
        return None

    # 复制结果，避免后续成本核算过程意外修改共享价格库对象。
    result = dict(reference)
    result["match_quality"] = quality
    result["unit_compatible"] = _price_units_compatible(source_unit, reference.get("unit"))
    result["match_score"] = score
    return result

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
    budget_numeric = None
    limit_type = "unspecified"
    price_book = []
    equipment_list_from_db = []
    rag_context = ""
    
    try:
        document = document_crud.get_document_by_id(db, document_id, user_id, tenant_id)
        
        # 优先从 FinancialMetadata 查询最高投标限价 (max_price_limit) 与采购总预算 (budget)
        from app.db.models.metadata import FinancialMetadata, EngineeringMetadata
        fin_md = db.query(FinancialMetadata).filter(
            FinancialMetadata.document_id == document_id,
            FinancialMetadata.tenant_id == tenant_id
        ).first()
        if fin_md:
            if fin_md.max_price_limit and isinstance(fin_md.max_price_limit, dict) and fin_md.max_price_limit.get("amount"):
                try:
                    budget_numeric = float(fin_md.max_price_limit["amount"])
                    budget_limit = f"最高投标限价 ¥{budget_numeric:,.2f}"
                    limit_type = "max_price_limit"
                except (ValueError, TypeError) as e:
                    logger.warning(f"CostAgent 解析最高投标限价失败: {fin_md.max_price_limit}, error: {e}")
            elif fin_md.budget and isinstance(fin_md.budget, dict) and fin_md.budget.get("amount"):
                try:
                    budget_numeric = float(fin_md.budget["amount"])
                    budget_limit = f"采购总预算 ¥{budget_numeric:,.2f}"
                    limit_type = "budget"
                except (ValueError, TypeError) as e:
                    logger.warning(f"CostAgent 解析采购总预算失败: {fin_md.budget}, error: {e}")

        if budget_numeric is None and document and document.parsed_metadata:
            raw_budget_limit = document.parsed_metadata.get("budget_limit") or (document.parsed_metadata.get("cost_analysis") or {}).get("budget_limit")
            if raw_budget_limit:
                try:
                    import re
                    cleaned_budget = re.sub(r'[^\d.]', '', str(raw_budget_limit))
                    if cleaned_budget:
                        budget_numeric = float(cleaned_budget)
                        budget_limit = str(raw_budget_limit)
                        limit_type = "budget_limit"
                except Exception as e:
                    logger.warning(f"CostAgent 解析预算数字失败: {raw_budget_limit}, error: {e}")
            
        # 获取当前租户的全维度价格参考库
        price_query = db.query(MarketPriceReference)
        if tenant_id and tenant_id != 'default':
            price_query = price_query.filter(MarketPriceReference.tenant_id == tenant_id)
        price_refs = price_query.all()
        if not price_refs:
            price_refs = db.query(MarketPriceReference).all()

        price_book = [
            {
                "item_name": ref.item_name,
                "brand": ref.brand or "",
                "spec": ref.spec or "",
                "model": ref.model or "",
                "manufacturer": ref.manufacturer or "",
                "unit_price": ref.unit_price,
                "unit": ref.unit,
                "remark": ref.remark or ""
            }
            for ref in price_refs
        ]

        # 获取工程元数据中已经提取的设备明细清单（若有）
        from app.db.models.metadata import EngineeringMetadata
        eng_meta = db.query(EngineeringMetadata).filter(
            EngineeringMetadata.document_id == document_id
        ).first()
        if eng_meta and hasattr(eng_meta, "main_equipment_list") and eng_meta.main_equipment_list:
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

    # 当工程元数据为空时，成本核算仍使用现有 RAG 工具补充原文，避免空清单直接进入核算流程。
    if not equipment_list_from_db:
        rag_context = _get_cost_rag_context(document_id, tenant_id)

    # 提取纯净工程设备列表
    BATCH_SIZE = 100
    raw_batches = [
        equipment_list_from_db[i:i + BATCH_SIZE]
        for i in range(0, len(equipment_list_from_db), BATCH_SIZE)
    ] if equipment_list_from_db else [[]]

    logger.info(f"开始成本核算节点：共 {len(equipment_list_from_db)} 项设备，分 {len(raw_batches)} 批并发处理 (每批 ~{BATCH_SIZE} 项)，全维度价格库共 {len(price_book)} 项。")

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def process_single_batch(batch_idx: int, batch_items: list) -> tuple[int, list, str]:
        """处理单批次设备的轻量成本对标与测算 (极简 Prompt, 零 RAG 重复广播)"""
        candidate_price_book = filter_candidate_price_book(batch_items, price_book, max_candidates=40)
        
        # 仅组装必要的基础待对标属性，大幅降低 Input Tokens
        prompt_items = [
            {
                "item_index": idx,
                "name": item.get("item_name") or item.get("name") or "",
                "specifications": item.get("specifications") or item.get("spec_requirement") or "",
                "quantity": item.get("quantity") if item.get("quantity") is not None else item.get("qty"),
                "unit": item.get("unit"),
                "parent_item": item.get("parent_item"),
                "brand_requirements": item.get("brand_requirements") or ""
            }
            for idx, item in enumerate(batch_items)
        ]

        logger.info(f"🚀 [5路并发核算] 处理第 {batch_idx + 1}/{len(raw_batches)} 批设备 ({len(prompt_items)} 项待匹配, 候选价格条目: {len(candidate_price_book)} 项)")

        rag_context_block = (
            f"\n【通用 RAG 工具返回的招标原文上下文】:\n{rag_context}\n"
            if rag_context
            else ""
        )
        batch_prompt = f"""
你是一位资深的工程与设备成本核算专家。
请分析以下待对标的【设备需求清单（当前批次）】，并将其与企业内部【全维度价格参考库（自有设备候选库）】进行智能通用语义匹配与参数对标。

【待对标设备清单 (当前批次共 {len(prompt_items)} 项)】:
{json.dumps(prompt_items, ensure_ascii=False, indent=2)}

【企业全维度价格参考库 (自有设备候选库)】:
{json.dumps(candidate_price_book, ensure_ascii=False, indent=2)}
{rag_context_block}

【智能对标与防重复计价核心规则】:
1. 必须对清单中的每一项设备按 item_index (0, 1, 2...) 输出对应的对标结果。
   - 如果待对标设备清单为空，必须从 RAG 原文上下文中提取明确出现的可计价设备、材料或服务行，再输出对应结果；原文没有明确数量时数量不得臆造。
2. 【成套总成 vs 子项防重复计价】:
   - 若某成套主设备（如开关柜、箱变）在价格库中匹配到了整套指导价：
     - 该成套主设备给出正常的 ref_price；
     - 其名下所有的细分子部件（parent_item 指向该设备的条目），其 ref_price 必须强制设为 0.0，并在 comparison_note 中明确标明：“已包含在成套打包统价中，不重复计费，仅作技术规格审核”。
   - 若成套设备在价格库中未匹配到整套价格，而内部元器件匹配到了散件单价：
     - 各底层元器件按单件单价正常匹配 ref_price；成套设备自身 ref_price 设为 0.0，并在 comparison_note 中注明：“成套总成本由名下各底层元器件明细汇总核算”。
3. 【品类粒度与量纲对齐（严禁跨粒度强行挂靠）】:
   - 当标书清单项为具体的单体原材料或独立构件（如具体规格的型材、线缆、钢材、接地极等，单位为米/根/吨）：
   - 价格库中必须有对应的单体材料才能匹配，绝对禁止强行挂靠到“整套工程系统包（单位为项/套）”上！若无单体价格，判定为“未匹配”（ref_price = 0.0, match_quality = "未匹配"）。
4. 【置信度判定】:
   - 名称与参数高度吻合为 "精准匹配"；同类同等替代物为 "模糊匹配"；价格库完全无对应产品或量级不匹配为 "未匹配" (ref_price = 0.0)。
5. 【简洁性约束】:
   - comparison_note 字段必须简明扼要（1~2 句话，50 字以内），严禁长篇大论，严禁在 JSON 字符串内部包含未经转义的多行回车换行！
"""
        try:
            batch_resp = llm_service.generate_structured_output(
                prompt=batch_prompt,
                schema_cls=BatchMatchResult,
                temperature=0.0,
                tenant_id=tenant_id,
            )
            matches = []
            summary = ""
            if batch_resp:
                if hasattr(batch_resp, "matches"):
                    matches = batch_resp.matches
                    summary = getattr(batch_resp, "batch_summary", "")
                elif hasattr(batch_resp, "items"):
                    # 兼容单元测试 Mock 及遗留结构
                    for idx_item, it in enumerate(batch_resp.items):
                        it_dict = it if isinstance(it, dict) else it.model_dump()
                        match_obj = ItemMatchOutput(
                            item_index=idx_item,
                            ref_price=it_dict.get("ref_price") or 0.0,
                            matched_name=it_dict.get("matched_name") or it_dict.get("name") or "",
                            matched_brand=it_dict.get("matched_brand") or "",
                            matched_model=it_dict.get("matched_model") or "",
                            matched_manufacturer=it_dict.get("matched_manufacturer") or "",
                            match_quality=it_dict.get("match_quality") or "未匹配",
                            comparison_note=it_dict.get("comparison_note") or "",
                            warning=it_dict.get("warning") or "",
                            name=it_dict.get("name"),
                            qty=it_dict.get("qty"),
                            unit=it_dict.get("unit"),
                            subtotal=it_dict.get("subtotal"),
                            spec_requirement=it_dict.get("spec_requirement")
                        )
                        matches.append(match_obj)
                    summary = getattr(batch_resp, "analysis_summary", "")
            return batch_idx, matches, summary
        except Exception as e:
            logger.error(f"第 {batch_idx + 1} 批成本测算解析失败: {e}")
            return batch_idx, [], ""

    # 使用 ThreadPoolExecutor 进行 5 路并发调度，严格按批次索引保序
    max_workers = min(5, len(raw_batches)) if raw_batches else 1
    logger.info(f"启动 ThreadPoolExecutor 并发核算，并发量: {max_workers}，共 {len(raw_batches)} 批...")
    
    batch_results = [None] * len(raw_batches)
    overall_summary = ""

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_idx = {
            executor.submit(process_single_batch, idx, b_items): idx
            for idx, b_items in enumerate(raw_batches)
        }
        for future in as_completed(future_to_idx):
            b_idx, b_matches, b_summary = future.result()
            batch_results[b_idx] = b_matches
            if b_summary and not overall_summary:
                overall_summary = b_summary

    # 本地高保真组装：死锁还原原始字段、执行打包置零与高精度乘法
    from app.utils.table_utils import normalize_section_name
    calculated_items = []
    total_cost = 0.0
    unmatched_count = 0

    if not equipment_list_from_db:
        # 降级兜底处理：当 DB 中未预先提取设备清单时，直接根据 LLM 对标结果生成
        for b_matches in batch_results:
            for m in (b_matches or []):
                ref_p = float(getattr(m, "ref_price", 0.0) or 0.0)
                raw_q = getattr(m, "qty", 1.0)
                safe_q = float(raw_q) if raw_q is not None else 1.0
                subtot = getattr(m, "subtotal", None)
                if subtot is None:
                    subtot = round(safe_q * ref_p, 2)
                else:
                    subtot = float(subtot)
                total_cost += subtot
                m_name = getattr(m, "name", "") or getattr(m, "matched_name", "") or f"设备项_{getattr(m, 'item_index', 0)}"
                calculated_items.append({
                    "item_code": getattr(m, "item_code", None),
                    "name": m_name,
                    "spec_requirement": getattr(m, "spec_requirement", "") or "",
                    "qty": safe_q,
                    "unit": getattr(m, "unit", None) or orig_item.get("unit"),
                    "parent_item": getattr(m, "parent_item", None),
                    "root_item": getattr(m, "root_item", None),
                    "tree_level": getattr(m, "tree_level", 1) or 1,
                    "per_set_qty": getattr(m, "per_set_qty", None),
                    "section_name": normalize_section_name(getattr(m, "section_name", None)),
                    "key_parameters": getattr(m, "key_parameters", []) or [],
                    "brand_requirements": getattr(m, "brand_requirements", "") or "",
                    "matched_name": getattr(m, "matched_name", "") or m_name,
                    "matched_brand": getattr(m, "matched_brand", "") or "",
                    "matched_model": getattr(m, "matched_model", "") or "",
                    "matched_manufacturer": getattr(m, "matched_manufacturer", "") or "",
                    "ref_price": ref_p,
                    "subtotal": subtot,
                    "match_quality": getattr(m, "match_quality", "精准匹配") or "精准匹配",
                    "warning": getattr(m, "warning", "") or "",
                    "comparison_note": getattr(m, "comparison_note", "") or "",
                    "remark": str(getattr(m, "remark", "") or "").strip() or resolve_price_reference_remark(m, price_book),
                })
    else:
        for batch_idx, b_items in enumerate(raw_batches):
            b_matches = batch_results[batch_idx] or []
            match_map = {}
            for m in b_matches:
                try:
                    m_idx = int(m.item_index)
                    match_map[m_idx] = m
                except (ValueError, TypeError):
                    continue

            for local_idx, orig_item in enumerate(b_items):
                match_info = match_map.get(local_idx)

                # 1. 基础字段 100% 忠实死锁还原
                item_name = orig_item.get("item_name") or orig_item.get("name") or "未命名项"
                spec_req = orig_item.get("specifications") or orig_item.get("spec_requirement") or ""
                raw_qty = orig_item.get("quantity") if orig_item.get("quantity") is not None else orig_item.get("qty")
                unit = orig_item.get("unit")
                parent = orig_item.get("parent_item")
                root = orig_item.get("root_item")
                tree_lvl = orig_item.get("tree_level") or 1
                per_set = orig_item.get("per_set_quantity") if orig_item.get("per_set_quantity") is not None else orig_item.get("per_set_qty")
                sec_name = normalize_section_name(orig_item.get("section_name"))
                key_params = orig_item.get("key_parameters") or []
                brand_req = orig_item.get("brand_requirements") or ""

                # 没有数量和单位的标题/说明节点只用于还原 BOM 树，不能参与企业价格库匹配。
                is_structural_node = raw_qty is None and not str(unit or "").strip()

                # 2. 对标字段注入
                ref_price = float(match_info.ref_price or 0.0) if match_info else 0.0
                matched_name = match_info.matched_name if match_info else ""
                matched_brand = match_info.matched_brand if match_info else ""
                matched_model = match_info.matched_model if match_info else ""
                matched_mfr = match_info.matched_manufacturer if match_info else ""
                match_quality = match_info.match_quality if match_info else "未匹配"
                note = match_info.comparison_note if match_info else ""
                warning = match_info.warning if match_info else ""
                remark = (
                    str(getattr(match_info, "remark", "") or "").strip()
                    if match_info
                    else ""
                ) or resolve_price_reference_remark(match_info, price_book)

                # 模型未返回有效价格时，用名称/规格/计量单位的确定性规则补齐明显匹配，
                # 解决大批量 BOM 中模型漏回 item_index 或漏填 matched_name 的问题。
                if not is_structural_node and (match_info is None or ref_price <= 0):
                    local_match = find_local_price_reference(orig_item, price_book)
                    if local_match:
                        ref_price = float(local_match.get("unit_price") or 0.0)
                        matched_name = str(local_match.get("item_name") or "")
                        matched_brand = str(local_match.get("brand") or "")
                        matched_model = str(local_match.get("model") or local_match.get("spec") or "")
                        matched_mfr = str(local_match.get("manufacturer") or "")
                        match_quality = str(local_match.get("match_quality") or "模糊匹配")
                        if not _price_units_compatible(unit, local_match.get("unit")):
                            ref_price = 0.0
                            warning = (
                                f"已找到价格库候选，但清单单位{unit or '未填写'}与库单位"
                                f"{local_match.get('unit') or '未填写'}不一致，未直接计价"
                            )
                        else:
                            warning = warning or ""
                        remark = str(local_match.get("remark") or "").strip()

                if is_structural_node:
                    ref_price = 0.0
                    matched_name = ""
                    matched_brand = ""
                    matched_model = ""
                    matched_mfr = ""
                    match_quality = "结构节点"
                    warning = ""
                    remark = ""

                # 3. 防重复打包计价置零安全保护
                if ("不重复" in note and "计算" in note) or ("合并" in note and "计价" in note) or ("已包含" in note and "统价" in note) or ("已包含" in note and "打包" in note):
                    ref_price = 0.0

                # 4. 本地高精度小计计算
                safe_qty = float(raw_qty) if raw_qty is not None else 1.0
                subtotal = round(safe_qty * ref_price, 2)

                if ref_price <= 0 and not is_structural_node:
                    unmatched_count += 1
                    if match_quality not in ["精准匹配", "模糊匹配"]:
                        match_quality = "未匹配"
                    if not warning:
                        warning = "企业价格库暂无参考指导单价"

                total_cost += subtotal

                item_dict = {
                    "item_code": orig_item.get("item_code"),
                    "name": item_name,
                    "spec_requirement": spec_req,
                    "qty": safe_qty,
                    "unit": unit,
                    "parent_item": parent,
                    "root_item": root,
                    "tree_level": tree_lvl,
                    "per_set_qty": per_set,
                    "section_name": sec_name,
                    "key_parameters": key_params,
                    "brand_requirements": brand_req,
                    "is_structural": is_structural_node,
                    "matched_name": matched_name,
                    "matched_brand": matched_brand,
                    "matched_model": matched_model,
                    "matched_manufacturer": matched_mfr,
                    "ref_price": ref_price,
                    "subtotal": subtotal,
                    "match_quality": match_quality,
                    "warning": warning,
                    "comparison_note": note,
                    "remark": remark,
                }
                calculated_items.append(item_dict)

    # 5. 执行自底向上树形层级汇总（计算成套母项小计与折合单价，并以顶层根节点汇总项目预估总成本）
    from app.services.cost_service import rollup_hierarchical_cost_items
    calculated_items, total_cost, unmatched_count = rollup_hierarchical_cost_items(calculated_items)
    
    # 预算对比与风险预警
    budget_status = "预算未设置"
    
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

    logger.info(f"成本核算完成，总估算成本: {total_cost}，预算状态: {budget_status}，未匹配项: {unmatched_count}。")

    # 同步落盘写入 cost_estimates 实体数据表
    try:
        from app.db.models.ai_analysis import CostEstimate
        # 清理该文档已有的旧测算记录
        db.query(CostEstimate).filter(CostEstimate.document_id == document_id).delete()

        def _optional_float(value):
            if value is None or value == "":
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        def _optional_int(value):
            if value is None or value == "":
                return None
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

        for sort_order, item in enumerate(calculated_items):
            raw_item_qty = item.get("qty")
            safe_qty = float(raw_item_qty) if raw_item_qty is not None else 1.0
            raw_unit_price = item.get("matched_ref_price") or item.get("ref_price") or 0.0
            try:
                safe_unit_price = float(raw_unit_price)
            except (ValueError, TypeError):
                safe_unit_price = 0.0
                
            raw_subtotal = item.get("subtotal") or 0.0
            try:
                safe_subtotal = float(raw_subtotal)
            except (ValueError, TypeError):
                safe_subtotal = 0.0
                
            # 提取品牌、型号与生产厂商（仅采用对标匹配或用户填写的品牌、型号与厂家，无则直接留空，严禁回退采用标书要求文字）
            effective_brand = str(item.get("matched_brand") or item.get("brand") or "").strip()
            effective_model = str(item.get("matched_model") or item.get("model") or "").strip()
            effective_mfg = str(item.get("matched_manufacturer") or item.get("manufacturer") or "").strip()

            est = CostEstimate(
                tenant_id=tenant_id,
                document_id=document_id,
                project_id=document.project_id if document else None,
                item_code=str(item.get("item_code") or "").strip() or None,
                item_name=str(item.get("name") or "未命名项"),
                quantity=safe_qty,
                unit=str(item.get("unit")) if item.get("unit") is not None else None,
                unit_price=safe_unit_price,
                calculated_total=safe_subtotal,
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
                tree_level=_optional_int(item.get("tree_level")),
                per_set_qty=_optional_float(item.get("per_set_qty")),
                per_set_quantity=_optional_float(item.get("per_set_quantity") or item.get("per_set_qty")),
                section_name=str(item.get("section_name") or "") if item.get("section_name") else None,
                remark=str(item.get("remark") or item.get("comparison_note") or item.get("warning") or "").strip() or None,
                sort_order=sort_order,
            )
            db.add(est)
        db.commit()
        logger.info(f"成功将 {len(calculated_items)} 条 BOM 测算细目同步落盘至 cost_estimates 数据表！")
    except Exception as db_err:
        db.rollback()
        logger.warning(f"同步落盘至 cost_estimates 数据表发生非致命异常: {db_err}")
    
    summary = f"完成 BOM 成本核算：包含 {len(calculated_items)} 项设备，预估总成本 ¥{total_cost:,.2f}"
    if unmatched_count > 0:
        summary += f"（{unmatched_count} 项未在库中找到参考价）"

    emit_agent_log("info", summary, extra={"type": "worker_complete", "worker": "cost_estimation", "status": "success", "summary": summary, "document_id": document_id})
    
    return {
        "cost_analysis": {
            "total_cost": total_cost,
            "budget_limit": budget_limit,
            "budget_numeric": budget_numeric,
            "limit_type": limit_type,
            "budget_status": budget_status,
            "unmatched_count": unmatched_count,
            "analysis_summary": overall_summary or "已完成各批次设备成本测算",
            "items": calculated_items
        },
        "completed_steps": ["cost_estimation"],
        "worker_summaries": [{
            "worker": "cost_estimation",
            "status": "success",
            "summary": summary
        }]
    }
