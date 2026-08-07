"""
招投标全量数据库直查工具集 (bid_db_tools.py)

功能：
提供供 LangChain / LangGraph Agent 调用的标准 @tool 查库工具。
涵盖系统全量数据库表结构 (company_profiles, company_qualifications, market_price_references, 
timeline_metadata, financial_metadata, qualification_metadata, engineering_metadata, 
evaluation_metadata, cost_estimates, risk_items, qualification_matches, documents, projects, users)，
实现零幻觉的绝对 SQL 直查，直接返回数据库存储的真实企业档案、资质证书、项目元数据、财务报价及合规要求。

遵循项目规范：
1. 全面使用中文注释与 Docstrings；
2. 全面使用 Type Hints 类型提示；
3. 使用 loguru 进行超详细调试日志记录；
4. 防御性编程与尽早返回 (Early Return)。
"""

import os
import json
from typing import Dict, Any, List, Optional
from loguru import logger
from sqlalchemy.orm import Session
from langchain_core.tools import tool

from app.db.session import SessionLocal
from app.db.models.business import CompanyProfileModel, CompanyQualification, MarketPriceReference
from app.db.models.metadata import (
    QualificationMetadata,
    FinancialMetadata,
    TimelineMetadata,
    EngineeringMetadata,
    EvaluationMetadata,
)
from app.db.models.project import Project as ProjectModel, Document as DocumentModel
from app.db.models.ai_analysis import QualificationMatch, RiskItem, CostEstimate
from app.db.models.user import User as UserModel
from app.utils.rmb_formatter import number_to_chinese_rmb


# ============================================================
# 全量数据库字段别名同义词映射字典 (Comprehensive Alias Mapping)
# ============================================================

ALIAS_MAP = {
    # 1. 企业基础工商档案 (company_profiles)
    "company_name": ["company_name", "公司名称", "投标人名称", "单位名称", "投标人全称", "投标人", "单位", "响应人名称", "投标单位", "企业名称"],
    "legal_representative": ["legal_representative", "法定代表人", "法人", "法人代表", "单位负责人", "法定代表人（签字）", "法定代表人或其委托代理人", "法定代表人姓名"],
    "authorized_delegate": ["authorized_delegate", "授权代表", "被授权人", "授权委托人", "签字代表", "委托代理人", "代表（签字）", "受托人", "代理人", "项目代表"],
    "credit_code": ["credit_code", "统一社会信用代码", "纳税人识别号", "税号", "营业执照注册号", "信用代码", "社会信用代码", "机构代码"],
    "registered_address": ["registered_address", "注册地址", "公司地址", "住所", "单位地址", "注册地", "经营地址", "详细地址", "通讯地址"],
    "contact_phone": ["contact_phone", "联系电话", "手机号", "电话", "联系方式", "固定电话", "联系人电话"],
    "email": ["email", "电子邮箱", "邮箱", "email", "e-mail", "联系邮箱", "企业邮箱"],
    "bank_name": ["bank_name", "开户银行", "基本户开户行", "结算银行", "开户行", "基本开户银行", "存款银行", "基本户银行"],
    "bank_account": ["bank_account", "银行账号", "基本户账号", "结算账号", "账号", "基本户银行账号", "银行卡号", "开户账号"],

    # 2. 项目与时间节点元数据 (timeline_metadata)
    "project_name": ["project_name", "项目名称", "招标项目名称", "采购项目名称", "工程名称", "项目全称", "招标工程名称"],
    "project_code": ["project_code", "project_id_code", "项目编号", "招标编号", "包件号", "标段编号", "采购编号", "项目代码", "招标代码"],
    "tender_segment": ["tender_segment", "标段名称", "包件名称", "标段", "包件", "分包名称"],
    "bid_deadline": ["bid_deadline", "投标截止时间", "开标时间", "递交截止时间", "截标时间", "开标日期"],
    "bid_validity_days": ["bid_validity_days", "投标有效期", "有效期", "投标有效期天数"],
    "construction_period": ["construction_period", "construction_period_description", "工期", "建设周期", "交货期", "服务期", "承诺工期", "交货期限", "完成时间", "服务期限"],

    # 3. 财务与价格元数据 (financial_metadata & cost_estimates)
    "bid_price_numeric": ["bid_price_numeric", "total_price_numeric", "投标总价", "投标金额", "投标小写", "报价小写", "总报价", "投标总金额", "最终报价"],
    "bid_price_chinese": ["bid_price_chinese", "total_price_chinese", "投标大写", "报价大写", "汉字大写", "大写金额", "投标总金额大写"],
    "bid_bond": ["bid_bond", "投标保证金", "保证金", "投标担保", "保证金金额"],
    "performance_bond": ["performance_bond", "履约保证金", "履约担保", "履约保证"],
    "warranty_bond": ["warranty_bond", "质保金", "质量保证金", "保修金", "质保保证金"],
    "payment_milestones": ["payment_milestones", "付款方式", "付款节点", "支付方式", "结算方式", "付款条款", "支付节点"],
    "tax_rate_requirement": ["tax_rate_requirement", "税率", "增值税率", "税率要求"],
    "contract_price_type": ["contract_price_type", "计价方式", "合同计价形式", "承包方式", "价格类型"],

    # 4. 资格要求与核心团队 (qualification_metadata)
    "mandatory_qualifications": ["mandatory_qualifications", "资质门槛", "企业资质要求", "必备资质"],
    "personnel_requirements": ["personnel_requirements", "核心人员", "项目经理", "技术负责人", "项目团队", "人员配置"],
    "performance_requirements": ["performance_requirements", "历史业绩", "类似业绩", "同类业绩", "业绩门槛"],
    "invalid_bid_clauses": ["invalid_bid_clauses", "废标条款", "否决投标条款", "无效投标条款", "一票否决"],

    # 5. 工程与技术规范 (engineering_metadata)
    "main_equipment_list": ["main_equipment_list", "设备清单", "主要设备", "材料清单"],
    "mandatory_standards": ["mandatory_standards", "技术标准", "强制性标准", "规范要求"],

    # 6. 评审标准与办法 (evaluation_metadata)
    "evaluation_method": ["evaluation_method", "评标方法", "评标办法", "评审标准", "评标标准"],
}


def _match_alias_key(user_key: str) -> str:
    """归一化别名到标准数据库字段 key"""
    key_clean = user_key.lower().strip()
    for std_key, aliases in ALIAS_MAP.items():
        for alias in aliases:
            if alias.lower() in key_clean or key_clean in alias.lower():
                return std_key
    return key_clean


# ============================================================
# LangChain / LangGraph Agent 可调用的工具集合 (@tool)
# ============================================================

@tool
def query_company_profile_tool(field_key: str) -> str:
    """
    [数据库直查工具] 查询本公司的企业基础工商档案 (company_profiles 表)。
    涵盖全量字段：公司名称、法定代表人、授权代表、统一社会信用代码、注册地址、联系电话、电子邮箱、开户银行、银行账号等。

    :param field_key: 欲查询的字段名或中文引导词 (如 'company_name', '统一社会信用代码', '开户银行')
    :return: 数据库中存储的真实原值字符串
    """
    logger.info(f"🛠️ [DB Tool] query_company_profile_tool 被调用, 字段请求: '{field_key}'")
    std_key = _match_alias_key(field_key)
    logger.debug(f"🛠️ [DB Tool] 别名归一化对齐结果: '{field_key}' -> '{std_key}'")

    db: Session = SessionLocal()
    try:
        profile = db.query(CompanyProfileModel).first()

        if profile:
            val = getattr(profile, std_key, None)
            if val and str(val).strip():
                logger.info(f"🛠️ [DB Tool] 成功从数据库 (company_profiles.{std_key}) 查询到真实数据: '{val}'")
                return str(val).strip()

        logger.warning(f"🛠️ [DB Tool] 字段 '{field_key}' 在企业档案数据库中尚未录入")
        return f"[待补充: {field_key}]"

    except Exception as e:
        logger.exception(f"🛠️ [DB Tool] query_company_profile_tool 执行异常: {str(e)}")
        return f"[查询异常: {str(e)}]"
    finally:
        db.close()


@tool
def query_company_qualification_tool(cert_keyword: str) -> str:
    """
    [数据库直查工具] 查询企业资质与证书数据库 (company_qualifications 表)。
    根据关键字搜索已录入的资质证书，返回证书名称、等级、有效期。

    :param cert_keyword: 证书名称关键字（必须来自招标文件原文中明确要求的资质名称）
    :return: 匹配的资质证书记录文本
    """
    logger.info(f"🛠️ [DB Tool] query_company_qualification_tool 被调用, 关键字: '{cert_keyword}'")
    if not cert_keyword:
        return "[错误: 证书关键字不能为空]"

    db: Session = SessionLocal()
    try:
        kw = cert_keyword.strip()
        quals = db.query(CompanyQualification).filter(
            CompanyQualification.name.ilike(f"%{kw}%")
        ).all()

        if quals:
            res_list = []
            for q in quals:
                exp_str = f" (有效期至 {q.expiry_date})" if q.expiry_date else ""
                lvl_str = f" [等级/范围: {q.level}]" if q.level else ""
                res_list.append(f"{q.name}{lvl_str}{exp_str}")

            result_str = "; ".join(res_list)
            logger.info(f"🛠️ [DB Tool] 匹配到 {len(quals)} 条资质证书记录: {result_str}")
            return result_str

        logger.warning(f"🛠️ [DB Tool] 未找到包含关键字 '{cert_keyword}' 的资质证书记录")
        return f"[待手动补充资质证书: {cert_keyword}]"

    except Exception as e:
        logger.exception(f"🛠️ [DB Tool] query_company_qualification_tool 执行异常: {str(e)}")
        return f"[查询资质异常: {str(e)}]"
    finally:
        db.close()


@tool
def query_project_metadata_tool(document_id: str, field_key: str) -> str:
    """
    [数据库直查工具] 全量直查本次招标项目的元数据信息。
    支持跨表覆盖：
    - timeline_metadata (项目名称, 招标编号, 标段, 递交截止时间, 投标有效期, 工期描述)
    - qualification_metadata (强制性资质门槛, 核心人员要求, 历史业绩门槛, 废标条款)
    - engineering_metadata (主要设备清单, 强制性技术标准, 现场限制说明)
    - evaluation_metadata (评标办法, 总分与权重分配)
    - documents (包含解析元数据 parsed_metadata)

    :param document_id: 关联的招标文件 Document ID
    :param field_key: 查询字段 (如 'project_name', 'project_code', 'construction_period', 'bid_deadline', 'personnel_requirements', 'invalid_bid_clauses')
    :return: 项目元数据真实字符串
    """
    logger.info(f"🛠️ [DB Tool] query_project_metadata_tool 被调用, doc_id: '{document_id}', 字段: '{field_key}'")
    db: Session = SessionLocal()
    try:
        key_lower = field_key.lower()

        # 1. 查时间节点与基本信息 (timeline_metadata)
        meta = db.query(TimelineMetadata).filter(TimelineMetadata.document_id == document_id).first()
        if meta:
            if any(k in key_lower for k in ["项目名称", "工程名称", "project_name"]):
                if meta.project_name:
                    return meta.project_name
            elif any(k in key_lower for k in ["编号", "代码", "project_code", "project_id"]):
                if meta.project_id_code:
                    return meta.project_id_code
            elif any(k in key_lower for k in ["工期", "建设周期", "交货期", "construction_period"]):
                if meta.construction_period_description:
                    return meta.construction_period_description
                elif meta.construction_period_days:
                    return f"{meta.construction_period_days} 日历天"
            elif any(k in key_lower for k in ["截止时间", "开标时间", "bid_deadline"]):
                if meta.bid_deadline:
                    return str(meta.bid_deadline)
            elif any(k in key_lower for k in ["有效期", "validity"]):
                if meta.bid_validity_days:
                    return f"{meta.bid_validity_days} 天"
            elif any(k in key_lower for k in ["标段", "包件", "tender_segment"]):
                if meta.tender_segment:
                    return meta.tender_segment

        # 2. 查资格与人员要求 (qualification_metadata)
        qual_meta = db.query(QualificationMetadata).filter(QualificationMetadata.document_id == document_id).first()
        if qual_meta:
            if any(k in key_lower for k in ["人员", "项目经理", "技术负责人", "personnel"]):
                if qual_meta.personnel_requirements:
                    return json.dumps(qual_meta.personnel_requirements, ensure_ascii=False)
            elif any(k in key_lower for k in ["废标", "否决", "invalid_bid"]):
                if qual_meta.invalid_bid_clauses:
                    return json.dumps(qual_meta.invalid_bid_clauses, ensure_ascii=False)
            elif any(k in key_lower for k in ["业绩", "performance"]):
                if qual_meta.performance_requirements:
                    return json.dumps(qual_meta.performance_requirements, ensure_ascii=False)

        # 3. 查工程与设备清单 (engineering_metadata)
        eng_meta = db.query(EngineeringMetadata).filter(EngineeringMetadata.document_id == document_id).first()
        if eng_meta:
            if any(k in key_lower for k in ["设备", "清单", "equipment"]):
                if eng_meta.main_equipment_list:
                    return json.dumps(eng_meta.main_equipment_list, ensure_ascii=False)
            elif any(k in key_lower for k in ["标准", "规范", "standard"]):
                if eng_meta.mandatory_standards:
                    return json.dumps(eng_meta.mandatory_standards, ensure_ascii=False)
            elif any(k in key_lower for k in ["工程", "engineering", "技术", "特殊工况", "现场"]):
                # 通用工程查询 → 返回完整 engineering_metadata
                result = {k: v for k, v in eng_meta.__dict__.items() if not k.startswith('_')}
                return json.dumps(result, ensure_ascii=False, default=str)

        # 4. 查评标方法与权重 (evaluation_metadata)
        eval_meta = db.query(EvaluationMetadata).filter(EvaluationMetadata.document_id == document_id).first()
        if eval_meta:
            if any(k in key_lower for k in ["评标", "评审", "evaluation", "评分", "权重"]):
                if eval_meta.evaluation_method:
                    return eval_meta.evaluation_method

        # 5. 查 Document 实体及 parsed_metadata
        doc = db.query(DocumentModel).filter(DocumentModel.id == document_id).first()
        if doc:
            if any(k in key_lower for k in ["项目名称", "工程名称", "project_name"]):
                if getattr(doc, "project_name", None):
                    return doc.project_name
                elif doc.filename:
                    clean_name = doc.filename.replace("Frontend Uploads (", "").replace(")", "").replace(".docx", "").replace(".pdf", "")
                    return clean_name.strip()
            elif any(k in key_lower for k in ["编号", "代码", "project_code", "project_id"]):
                if getattr(doc, "project_code", None):
                    return doc.project_code
            elif doc.parsed_metadata:
                val = doc.parsed_metadata.get(field_key) or doc.parsed_metadata.get("project_name")
                if val:
                    return str(val)

        logger.warning(f"🛠️ [DB Tool] 项目元数据中未查到 '{field_key}'")
        return f"[待补充: {field_key}]"

    except Exception as e:
        logger.exception(f"🛠️ [DB Tool] query_project_metadata_tool 执行异常: {str(e)}")
        return f"[查询元数据异常: {str(e)}]"
    finally:
        db.close()


@tool
def query_financial_quotation_tool(document_id: str, field_key: str) -> str:
    """
    [数据库直查工具] 全量查询财务报价、BOM 清单、分项造价、保证金及付款条款数据 (financial_metadata / cost_estimates / market_price_references 表)。
    支持查询【分项报价清单 (cost_estimates/bom)】并输出各分项名称、品牌、数量、单价与小计，也可输出阿拉伯数字总价、标准【汉字大写金额】、投标保证金、履约保证金及付款节点要求。

    :param document_id: 招标文件 ID
    :param field_key: 查询类型 ('cost_estimates', 'bom_list', 'total_price_numeric', 'total_price_chinese', 'bid_price_chinese', 'bid_bond', 'performance_bond', 'payment_milestones')
    :return: 分项报价明细列表、价格、保证金或付款条款字符串
    """
    logger.info(f"🛠️ [DB Tool] query_financial_quotation_tool 被调用, doc_id: '{document_id}', 字段: '{field_key}'")
    db: Session = SessionLocal()
    try:
        key_lower = field_key.lower()

        # 1. 查财务元数据中的保证金与付款节点
        fin_meta = db.query(FinancialMetadata).filter(FinancialMetadata.document_id == document_id).first()
        if fin_meta:
            if "bond" in key_lower or "保证金" in key_lower:
                if fin_meta.bid_bond:
                    return json.dumps(fin_meta.bid_bond, ensure_ascii=False)
            elif "payment" in key_lower or "付款" in key_lower or "支付" in key_lower:
                if fin_meta.payment_milestones:
                    return json.dumps(fin_meta.payment_milestones, ensure_ascii=False)

        # 2. 查询成本测算总价与大写转换
        cost_items = db.query(CostEstimate).filter(CostEstimate.document_id == document_id).all()
        
        # 针对分项清单、BOM 表或分项单价/合价查询，返回每行精细列表
        if any(k in key_lower for k in ["cost", "bom", "item", "清单", "明细", "分项", "配置", "设备", "sub", "quote", "报价"]):
            if not cost_items:
                return "[待补充: 成本测算与 BOM 分项清单数据库尚未录入]"
            res_items = []
            for item in cost_items:
                brand_str = f" [品牌: {item.brand}]" if getattr(item, 'brand', None) else ""
                spec_str = f" [规格: {item.spec}]" if getattr(item, 'spec', None) else ""
                res_items.append(
                    f"- {item.item_name}{brand_str}{spec_str} | 数量: {item.quantity}{item.unit} | 参考单价: {item.unit_price}元 | 测算合计合价(总价): {item.calculated_total}元 | 备注: {getattr(item, 'remark', '')}"
                )
            logger.info(f"🛠️ [DB Tool] 成功查得并回传 {len(res_items)} 条 BOM 分项成本报价明细")
            return "\n".join(res_items)

        if not cost_items:
            return "[待补充: 财务总报价与分项测算数据尚未录入]"

        total_price = sum(item.calculated_total for item in cost_items)

        if any(k in key_lower for k in ["大写", "chinese"]):
            chinese_upper = number_to_chinese_rmb(total_price)
            logger.info(f"🛠️ [DB Tool] 成功计算投标总价汉字大写: {total_price} -> '{chinese_upper}'")
            return chinese_upper
        else:
            num_str = f"{total_price:,.2f}"
            logger.info(f"🛠️ [DB Tool] 成功查询投标总价阿拉伯数字: '{num_str}' 元")
            return num_str

    except Exception as e:
        logger.exception(f"🛠️ [DB Tool] query_financial_quotation_tool 执行异常: {str(e)}")
        return f"[查询财务报价异常: {str(e)}]"
    finally:
        db.close()


@tool
def query_market_price_reference_tool(item_name: str) -> str:
    """
    [数据库直查工具] 查询市场设备/材料参考指导价以及 BOM 历史报价数据库 (market_price_references 及 cost_estimates 表)。
    适用于查询特定设备（如某核心主机、某配套总成）、软硬件、材料、耗材的参考单价、品牌、规格型号以及系统测算的单价和分项合价。

    :param item_name: 品目/设备/材料名称关键字（支持单关键词或复合关键词，如 'XXX主设备'、'XXX配件 某推荐品牌' 或 '某设备名称 XXX技术规范'）
    :return: 包含品名、品牌、规格、参考单价、建议数量与总价等完整维度的指导意见
    """
    logger.info(f"🛠️ [DB Tool] query_market_price_reference_tool 被调用, 品目关键字: '{item_name}'")
    if not item_name:
        return "[错误: 品目关键字不能为空]"

    db: Session = SessionLocal()
    try:
        clean_kw = item_name.strip()
        # 1. 优先尝试完全精准模糊匹配
        items = db.query(MarketPriceReference).filter(
            MarketPriceReference.item_name.ilike(f"%{clean_kw}%")
        ).all()

        # 2. 如果无精准结果，则采取多关键字切分匹配（如 "XXX核心设备 某厂牌 XXX型号" -> ["XXX核心设备", "某厂牌"]）
        if not items and (" " in clean_kw or "/" in clean_kw or "—" in clean_kw or "-" in clean_kw):
            tokens = [t for t in clean_kw.replace("/", " ").replace("—", " ").replace("-", " ").split() if len(t) >= 2]
            for t in tokens:
                sub_res = db.query(MarketPriceReference).filter(
                    MarketPriceReference.item_name.ilike(f"%{t}%")
                ).all()
                for r in sub_res:
                    if r.id not in [x.id for x in items]:
                        items.append(r)

        res_list = []
        if items:
            for it in items:
                brand_str = f" [品牌: {it.brand}]" if it.brand else ""
                spec_str = f" [规格: {it.spec}]" if it.spec else ""
                res_list.append(f"【市场参考单价】{it.item_name}{brand_str}{spec_str}: 单价 {it.unit_price}元/{it.unit} (说明: {getattr(it, 'remark', '')})")

        # 3. 联合直查本系统 CostEstimate 成本估算底单（能够提供真实的数量与合计合价/总价，弥补缺失）
        first_word = clean_kw.split()[0] if " " in clean_kw else clean_kw
        cost_matches = db.query(CostEstimate).filter(
            CostEstimate.item_name.ilike(f"%{first_word}%")
        ).all()
        if cost_matches:
            for c in cost_matches:
                brand_str = f" [品牌: {c.brand}]" if getattr(c, 'brand', None) else ""
                res_list.append(
                    f"【本期项目BOM实测记录】{c.item_name}{brand_str} | 推荐数量: {c.quantity}{c.unit} | 测算单价: {c.unit_price}元 | 分项估算总价(合价): {c.calculated_total}元"
                )

        if res_list:
            return "\n".join(res_list)

        return f"[未查到与 '{item_name}' 相关的参考指导价与合价]"

    except Exception as e:
        logger.exception(f"🛠️ [DB Tool] query_market_price_reference_tool 执行异常: {str(e)}")
        return f"[查询市场指导价异常: {str(e)}]"
    finally:
        db.close()


@tool
def query_evaluation_method_tool(document_id: str, detail_type: str = "method") -> str:
    """
    [数据库直查工具] 独立直查本招投标项目的评标方法、评标办法与评审打分细则 (evaluation_metadata 表)。
    可单独查询：
    - evaluation_method: 评标办法名称
    - total_score: 评标总分
    - weight_distribution: 商务/技术/价格权重分值分配 JSON
    - score_tree: 详细打分细则树 JSON

    :param document_id: 关联的招标文件 Document ID
    :param detail_type: 查询类型 ('method', 'weight', 'score_tree', 'all')
    :return: 评标办法与打分细则描述文本
    """
    logger.info(f"🛠️ [DB Tool] query_evaluation_method_tool 独立工具被调用, doc_id: '{document_id}', detail_type: '{detail_type}'")
    db: Session = SessionLocal()
    try:
        eval_meta = db.query(EvaluationMetadata).filter(EvaluationMetadata.document_id == document_id).first()
        if eval_meta:
            if (detail_type == "weight" or "weight" in detail_type) and eval_meta.weight_distribution:
                return json.dumps(eval_meta.weight_distribution, ensure_ascii=False)
            elif (detail_type == "score_tree" or "tree" in detail_type) and eval_meta.score_tree:
                return json.dumps(eval_meta.score_tree, ensure_ascii=False)
            elif eval_meta.evaluation_method:
                score_str = f" (总分: {eval_meta.total_score}分)" if eval_meta.total_score else ""
                logger.info(f"🛠️ [DB Tool] 查得真实评标办法: '{eval_meta.evaluation_method}{score_str}'")
                return f"{eval_meta.evaluation_method}{score_str}"

        logger.warning("🛠️ [DB Tool] DB 中未录入 evaluation_metadata，返回待补充标记")
        return "[待补充: 评标办法未录入系统]"

    except Exception as e:
        logger.exception(f"🛠️ [DB Tool] query_evaluation_method_tool 执行异常: {str(e)}")
        return f"[查询评标办法异常: {str(e)}]"
    finally:
        db.close()


def get_all_bid_db_tools() -> List[Any]:
    """获取所有 6 大数据库直查工具实例列表"""
    return [
        query_company_profile_tool,
        query_company_qualification_tool,
        query_project_metadata_tool,
        query_financial_quotation_tool,
        query_market_price_reference_tool,
        query_evaluation_method_tool,
    ]
