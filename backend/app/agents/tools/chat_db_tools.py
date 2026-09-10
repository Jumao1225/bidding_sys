"""前台 ChatAgent 专用的只读数据库工具适配层。"""

from typing import Any, Optional

from langchain_core.tools import tool
from loguru import logger

from app.agents.tools.security import validate_document_access
from app.core.context import current_tenant_id
from app.db.models.ai_analysis import CostEstimate
from app.db.models.business import CompanyProfileModel, MarketPriceReference
from app.db.session import SessionLocal

from app.agents.tools.bid_db_tools import (
    _match_alias_key,
    current_profile_id,
    query_company_qualification_tool as _query_company_qualification_tool,
    query_evaluation_method_tool as _query_evaluation_method_tool,
    query_financial_quotation_tool as _query_financial_quotation_tool,
    query_project_metadata_tool as _query_project_metadata_tool,
)


def _safe_document_tool_call(tool_instance: Any, document_id: str, arguments: dict[str, Any]) -> str:
    """统一校验文档权限后调用现有 ORM 直查工具。"""
    if not document_id or not validate_document_access(document_id):
        logger.warning("[Chat DB Tool] 拒绝访问无权限文档: document_id={}", document_id)
        return "[无权访问当前文档]"
    try:
        return _invoke_tool_function(tool_instance, arguments)
    except Exception as error:
        logger.exception(
            "[Chat DB Tool] 只读工具执行异常: tool={}, document_id={}, error={}",
            getattr(tool_instance, "name", "unknown"),
            document_id,
            error,
        )
        return f"[数据库查询异常: {error}]"


def _invoke_tool_function(tool_instance: Any, arguments: dict[str, Any]) -> str:
    """直接调用原始工具函数，避免嵌套 LangChain 工具事件。"""
    tool_function = getattr(tool_instance, "func", None)
    if not callable(tool_function):
        raise TypeError(
            f"工具 {getattr(tool_instance, 'name', 'unknown')} 未暴露可调用的原始函数"
        )

    logger.debug(
        "[Chat DB Tool] 直接调用原始查询函数，避免嵌套工具事件: tool={}",
        getattr(tool_instance, "name", "unknown"),
    )
    return str(tool_function(**arguments))


@tool
def query_company_profile_tool(field_key: str) -> str:
    """按当前租户和当前运行主体查询企业档案，不触发任何写入。"""
    db = SessionLocal()
    try:
        tenant_id = current_tenant_id.get()
        query = db.query(CompanyProfileModel)
        if tenant_id:
            query = query.filter(CompanyProfileModel.tenant_id == tenant_id)

        profile_id = current_profile_id.get()
        profile = query.filter(CompanyProfileModel.id == profile_id).first() if profile_id else None
        if profile is None:
            profile = query.filter(CompanyProfileModel.is_default == True).order_by(
                CompanyProfileModel.created_at.asc(),
                CompanyProfileModel.id.asc(),
            ).first()
        if profile is None:
            profile = query.order_by(
                CompanyProfileModel.created_at.asc(),
                CompanyProfileModel.id.asc(),
            ).first()
        if profile is None:
            return f"[待补充: {field_key}]"

        standard_key = _match_alias_key(field_key)
        value = getattr(profile, standard_key, None)
        if value is None or not str(value).strip():
            return f"[待补充: {field_key}]"
        logger.info(
            "[Chat DB Tool] 查询企业档案成功: field={}, tenant_id={}",
            standard_key,
            tenant_id,
        )
        return str(value).strip()
    except Exception as error:
        logger.exception("[Chat DB Tool] 查询企业档案异常: {}", error)
        return f"[查询企业档案异常: {error}]"
    finally:
        db.close()


@tool
def query_company_qualification_tool(
    cert_keyword: str = "",
    tenant_id: Optional[str] = None,
) -> str:
    """查询当前租户企业资质，复用现有资质数据库直查实现。"""
    return _invoke_tool_function(
        _query_company_qualification_tool,
        {"cert_keyword": cert_keyword, "tenant_id": tenant_id},
    )


@tool
def query_project_metadata_tool(document_id: str, field_key: str) -> str:
    """校验文档权限后查询项目元数据，只读数据库。"""
    return _safe_document_tool_call(
        _query_project_metadata_tool,
        document_id,
        {"document_id": document_id, "field_key": field_key},
    )


@tool
def query_financial_quotation_tool(
    document_id: str,
    field_key: str = "cost_estimates",
    header_columns_json: Optional[str] = None,
) -> str:
    """校验文档权限后查询报价和 BOM，只读数据库。"""
    return _safe_document_tool_call(
        _query_financial_quotation_tool,
        document_id,
        {
            "document_id": document_id,
            "field_key": field_key,
            "header_columns_json": header_columns_json,
        },
    )


@tool
def query_market_price_reference_tool(item_name: str) -> str:
    """按当前租户查询市场参考价和成本估算，只读数据库。"""
    if not item_name or not item_name.strip():
        return "[错误: 品目关键字不能为空]"

    db = SessionLocal()
    try:
        tenant_id = current_tenant_id.get()
        keyword = item_name.strip()
        market_query = db.query(MarketPriceReference).filter(
            MarketPriceReference.item_name.ilike(f"%{keyword}%")
        )
        cost_query = db.query(CostEstimate).filter(
            CostEstimate.item_name.ilike(f"%{keyword}%")
        )
        if tenant_id:
            market_query = market_query.filter(MarketPriceReference.tenant_id == tenant_id)
            cost_query = cost_query.filter(CostEstimate.tenant_id == tenant_id)

        results = [
            f"【市场参考单价】{item.item_name}"
            f" | 品牌: {getattr(item, 'brand', '')}"
            f" | 规格: {getattr(item, 'spec', '')}"
            f" | 单价: {item.unit_price}元/{item.unit}"
            for item in market_query.all()
        ]
        results.extend(
            f"【本期项目BOM实测记录】{item.item_name}"
            f" | 数量: {item.quantity}{item.unit}"
            f" | 单价: {item.unit_price}元"
            f" | 合价: {item.calculated_total}元"
            for item in cost_query.all()
        )
        return "\n".join(results) if results else f"[未查到与 '{item_name}' 相关的参考指导价]"
    except Exception as error:
        logger.exception("[Chat DB Tool] 查询市场参考价异常: {}", error)
        return f"[查询市场指导价异常: {error}]"
    finally:
        db.close()


@tool
def query_evaluation_method_tool(document_id: str, detail_type: str = "method") -> str:
    """校验文档权限后查询评标办法，只读数据库。"""
    return _safe_document_tool_call(
        _query_evaluation_method_tool,
        document_id,
        {"document_id": document_id, "detail_type": detail_type},
    )


def get_chat_db_tools() -> list[Any]:
    """返回前台 ChatAgent 使用的租户隔离只读数据库工具。"""
    return [
        query_company_profile_tool,
        query_company_qualification_tool,
        query_project_metadata_tool,
        query_financial_quotation_tool,
        query_market_price_reference_tool,
        query_evaluation_method_tool,
    ]
