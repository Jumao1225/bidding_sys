"""
Write Agent 专属数据与条款检索工具集

功能：
1. get_company_qualifications_tool: 查询资质中心数据库 (CompanyQualification)，读取公司已有资质证书信息及图片路径；
2. get_cost_estimation_data_tool: 提取成本测算与底价数据（BOM清单、总价、大写金额）；
3. retrieve_chapter_clause_requirements: 检索招投标文件中针对特定章节的具体填写说明、提示与约束条款。
"""

import json
from typing import Dict, Any, List, Optional
from loguru import logger
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.db.models.business import CompanyQualification
from app.services.rag_service import rag_service
from app.agents.nodes.writer_agent import num_to_rmb_chinese


def get_company_qualifications_tool(tenant_id: str = None) -> List[Dict[str, Any]]:
    """
    【资质中心数据库查询工具 - 严格多租户隔离】
    查询当前租户在资质中心已上传并解析的所有有效公司资质证书数据（包含证书名称、级别、到期时间与图片访问URL）。

    参数:
        tenant_id: 租户ID

    返回:
        资质证书列表 [ { "name": ..., "level": ..., "expiry_date": ..., "file_url": ..., "company_name": ... } ]
    """
    db: Session = SessionLocal()
    try:
        from app.core.context import current_tenant_id
        ctx_tenant = current_tenant_id.get()
        # 优先使用真实有效的租户 UUID（若显式传入的为 default-tenant 占位符，则优先使用 ContextVar 中的当前登录租户）
        effective_tenant = tenant_id if (tenant_id and tenant_id != "default-tenant") else (ctx_tenant or tenant_id or "default-tenant")

        # 严格进行多租户隔离查询，决不跨租户降级与全表扫描
        quals = db.query(CompanyQualification).filter(
            CompanyQualification.tenant_id == effective_tenant
        ).order_by(CompanyQualification.created_at.desc()).all()

        results = []
        for q in quals:
            expiry_str = q.expiry_date.strftime("%Y-%m-%d") if q.expiry_date else "长期有效"
            results.append({
                "id": q.id,
                "name": q.name or "未命名资质",
                "level": q.level or "通用",
                "company_name": q.company_name or "",
                "expiry_date": expiry_str,
                "file_url": q.file_url or ""
            })
        logger.info(f"成功从资质中心 DB 查询到 {len(results)} 条公司资质证书记录 (tenant_id={effective_tenant})")
        return results
    except Exception as e:
        logger.warning(f"查询公司资质证书数据库异常: {e}")
        return []
    finally:
        db.close()


def get_cost_estimation_data_tool(analysis_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    【成本测算与底价数据提取工具】
    从前序成本分析结果中提取 BOM 清单、参考底价、分项小计与开标总价（含人民币大写）。

    参数:
        analysis_data: 前序节点产出的分析字典 (包含 cost_analysis)

    返回:
        包含 cost_items, total_cost, total_cost_rmb 的结构化数据字典
    """
    cost_analysis = analysis_data.get("cost_analysis") or {}
    cost_items = cost_analysis.get("items", [])
    total_cost = cost_analysis.get("total_cost", 0.0)

    total_cost_rmb = num_to_rmb_chinese(total_cost) if total_cost > 0 else "零元整"

    return {
        "cost_items": cost_items,
        "total_cost": total_cost,
        "total_cost_rmb": total_cost_rmb,
        "budget_status": cost_analysis.get("budget_status", "符合预算要求")
    }


def retrieve_chapter_clause_requirements(document_id: str, chapter_title: str) -> str:
    """
    【章节特定条款/填写要求精细化检索工具】
    针对给定的章节标题（如“投标函”、“开标一览表”、“售后服务承诺”），利用 RAG 定位招标文件中该章节原有的“填写说明”、“注：”、“特定响应约束”。

    参数:
        document_id: 招标文档ID
        chapter_title: 章节标题 (如 "投标函", "法定代表人授权书")

    返回:
        检索到的招标文件章节填写要求与说明文本片段
    """
    if not document_id:
        return "未提供文档ID，使用默认格式要求"

    query = f"{chapter_title} 填写说明 填写要求 注意事项 注 格式要求"
    try:
        context = rag_service.search_bidding_document(
            document_id=document_id,
            query=query,
            top_k=4,
            disable_expansion=True
        )
        if context and len(context.strip()) > 30:
            logger.info(f"为章节 [{chapter_title}] 成功检索到相关特定条款要求，共 {len(context)} 字符")
            return context.strip()
    except Exception as e:
        logger.warning(f"检索章节 [{chapter_title}] 特定条款失败: {e}")

    return f"按招标文件【{chapter_title}】标准格式要求如实填报"


# ============================================================
# LangChain / ReAct Agent 工具包装器 (供 ChatAgent 调用)
# ============================================================
from langchain_core.tools import tool


@tool
def get_company_qualifications(tenant_id: str = None) -> str:
    """
    【我公司资质中心数据库查询工具 - 严格租户隔离】
    当用户询问本公司/我方拥有什么资质证书、特种许可证（如《承装（修、试）电力设施许可证》、《安全生产许可证》）、证书等级或到期时间时，调用此工具查询资质中心数据库。
    参数:
      - tenant_id: 可选，租户ID，默认自动提取当前会话认证租户
    """
    quals = get_company_qualifications_tool(tenant_id)
    if not quals:
        return "资质中心数据库中目前暂无记录。"
    return json.dumps(quals, ensure_ascii=False, indent=2)


@tool
def get_cost_estimation_data(document_id: str) -> str:
    """
    【我公司成本报价与底价数据查询工具】
    当用户询问本公司对该项目的成本报价、BOM设备清单、各部件参考指导单价、分项小计或总报价时，请务必且优先调用此工具查询已测算的成本数据。
    参数:
      - document_id: 必须提供，当前招标文档ID
    """
    db: Session = SessionLocal()
    try:
        from app.db.models.project import Document
        doc = db.query(Document).filter(Document.id == document_id).first()
        if not doc or not doc.parsed_metadata:
            return "数据库中暂无该项目的成本测算数据。"
        
        cost_analysis = doc.parsed_metadata.get("cost_analysis")
        if not cost_analysis:
            return "该项目尚未进行成本测算分析。"
            
        return json.dumps(cost_analysis, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"查询成本测算数据异常: {e}")
        return f"查询成本测算数据异常: {str(e)}"
    finally:
        db.close()


@tool
def fetch_chapter_clause_requirements(document_id: str, chapter_title: str) -> str:
    """
    【章节特定要求与约束检索工具】
    当用户询问招标文件中某个特定章节（如“投标函”、“售后服务”、“开标一览表”）的具体填写说明、注、格式要求或约束条件时，调用此工具。
    参数:
      - document_id: 必须提供，当前招标文档ID
      - chapter_title: 章节名称或标题 (如 "售后服务承诺", "投标函")
    """
    return retrieve_chapter_clause_requirements(document_id, chapter_title)


WRITER_TOOLS = [
    get_company_qualifications,
    get_cost_estimation_data,
    fetch_chapter_clause_requirements
]

