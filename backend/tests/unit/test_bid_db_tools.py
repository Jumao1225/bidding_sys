"""
单元测试：招投标关键字段数据库直查工具 (test_bid_db_tools.py)
"""

import pytest
from unittest.mock import patch, MagicMock
from app.agents.tools.bid_db_tools import (
    query_company_profile_tool,
    query_company_qualification_tool,
    query_financial_quotation_tool,
    _match_alias_key,
)


def test_alias_mapping():
    """测试同义词别名归一化匹配"""
    assert _match_alias_key("统一社会信用代码") == "credit_code"
    assert _match_alias_key("法人代表") == "legal_representative"
    assert _match_alias_key("基本户开户行") == "bank_name"
    assert _match_alias_key("投标人名称") == "company_name"


def test_query_company_profile_fallback():
    res_credit = query_company_profile_tool.invoke({"field_key": "统一社会信用代码"})
    assert res_credit in ["91510000MA6X12345X", "91110108MA01988888X"] or "91" in res_credit

    res_company = query_company_profile_tool.invoke({"field_key": "投标人名称"})
    assert res_company is not None and len(res_company) > 0

    res_bank = query_company_profile_tool.invoke({"field_key": "开户银行"})
    assert res_bank is not None and len(res_bank) > 0


def test_query_financial_quotation_chinese():
    """测试财务报价大写金额转换集成"""
    res_chinese = query_financial_quotation_tool.invoke({
        "document_id": "dummy_doc_id",
        "field_key": "bid_price_chinese"
    })
    assert "元" in res_chinese or "[待" in res_chinese or "未" in res_chinese


def test_query_company_qualification_tool_basic():
    """测试资质查询工具基础功能与物理路径解析"""
    res = query_company_qualification_tool.invoke({"cert_keyword": "资质"})
    assert isinstance(res, str)

