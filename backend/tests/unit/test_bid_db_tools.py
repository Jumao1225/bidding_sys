"""
单元测试：招投标关键字段数据库直查工具 (test_bid_db_tools.py)
"""

import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch, MagicMock
from app.agents.tools.bid_db_tools import (
    query_company_profile_tool,
    query_company_qualification_tool,
    query_financial_quotation_tool,
    _match_alias_key,
    resolve_company_profile,
)
from app.db.models import Base, CompanyProfileModel


def test_alias_mapping():
    """测试同义词别名归一化匹配"""
    assert _match_alias_key("统一社会信用代码") == "credit_code"
    assert _match_alias_key("法人代表") == "legal_representative"
    assert _match_alias_key("基本户开户行") == "bank_name"
    assert _match_alias_key("投标人名称") == "company_name"


def test_alias_mapping_should_prefer_longest_specific_label():
    """复合字段标签不能被“单位”等短别名误判为企业名称。"""
    assert _match_alias_key("投标单位代表姓名（签字）") == "authorized_delegate"
    assert _match_alias_key("单位地址") == "registered_address"


def test_query_company_profile_fallback():
    res_credit = query_company_profile_tool.invoke({"field_key": "统一社会信用代码"})
    assert res_credit in ["91510000MA6X12345X", "91110108MA01988888X"] or "91" in res_credit

    res_company = query_company_profile_tool.invoke({"field_key": "投标人名称"})
    assert res_company is not None and len(res_company) > 0

    res_bank = query_company_profile_tool.invoke({"field_key": "开户银行"})
    assert res_bank is not None and len(res_bank) > 0


def test_query_company_profile_with_contextvar():
    """测试通过 ContextVar 动态绑定不同企业档案"""
    from app.agents.tools.bid_db_tools import current_profile_id
    token = current_profile_id.set("non-existent-profile-id-fallback-test")
    try:
        # 当指定 ID 不存在时，应优雅回退到默认档案
        res = query_company_profile_tool.invoke({"field_key": "投标人名称"})
        assert res is not None and len(res) > 0
    finally:
        current_profile_id.reset(token)


def _create_profile_test_session():
    """创建仅包含企业档案表的内存数据库，隔离主体解析单元测试。"""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[CompanyProfileModel.__table__])
    session_factory = sessionmaker(bind=engine)
    return engine, session_factory()


def test_resolve_company_profile_should_prefer_requested_profile():
    """指定主体存在时，解析结果必须优先使用指定主体。"""
    engine, db = _create_profile_test_session()
    try:
        db.add_all([
            CompanyProfileModel(
                id="default-profile",
                profile_name="默认主体",
                company_name="默认公司",
                is_default=True,
                created_at=datetime.now(timezone.utc),
            ),
            CompanyProfileModel(
                id="selected-profile",
                profile_name="指定主体",
                company_name="四川石楠建设工程有限公司",
                is_default=False,
                created_at=datetime.now(timezone.utc) + timedelta(seconds=1),
            ),
        ])
        db.commit()

        result = resolve_company_profile(db, "selected-profile")

        assert result is not None
        assert result.id == "selected-profile"
        assert result.company_name == "四川石楠建设工程有限公司"
    finally:
        db.close()
        engine.dispose()


def test_resolve_company_profile_should_fallback_to_default_for_unknown_id():
    """指定主体不存在时，解析结果必须回退到默认主体。"""
    engine, db = _create_profile_test_session()
    try:
        db.add(CompanyProfileModel(
            id="default-profile",
            profile_name="默认主体",
            company_name="默认公司",
            is_default=True,
            created_at=datetime.now(timezone.utc),
        ))
        db.commit()

        result = resolve_company_profile(db, "missing-profile")

        assert result is not None
        assert result.id == "default-profile"
    finally:
        db.close()
        engine.dispose()


def test_resolve_company_profile_should_use_oldest_profile_without_default():
    """没有默认主体时，必须按创建时间稳定选择最早档案。"""
    engine, db = _create_profile_test_session()
    try:
        created_at = datetime.now(timezone.utc)
        db.add_all([
            CompanyProfileModel(
                id="new-profile",
                profile_name="较新主体",
                company_name="较新公司",
                is_default=False,
                created_at=created_at + timedelta(seconds=1),
            ),
            CompanyProfileModel(
                id="old-profile",
                profile_name="较早主体",
                company_name="较早公司",
                is_default=False,
                created_at=created_at,
            ),
        ])
        db.commit()

        result = resolve_company_profile(db)

        assert result is not None
        assert result.id == "old-profile"
    finally:
        db.close()
        engine.dispose()


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


def test_sort_cost_items_by_scope_and_hierarchy_pure_generic():
    """测试纯通用区域/标段聚合算法（零行业与零具体数据硬编码）"""
    from app.agents.tools.bid_db_tools import sort_cost_items_by_scope_and_hierarchy
    from types import SimpleNamespace

    # 构造通用抽象的跨区域乱序清单条目（包含二标段、一标段等抽象标识）
    raw_items = [
        SimpleNamespace(item_name="标的物C（第2标段）", section_name="", brand="品牌C", spec="参数C", calculated_total=100),
        SimpleNamespace(item_name="标的物A（第1标段）", section_name="", brand="品牌A", spec="参数A", calculated_total=500),
        SimpleNamespace(item_name="标的物D（第2标段）", section_name="", brand="品牌D", spec="参数D", calculated_total=200),
        SimpleNamespace(item_name="标的物B（第1标段）", section_name="", brand="品牌B", spec="参数B", calculated_total=300),
    ]

    sorted_res = sort_cost_items_by_scope_and_hierarchy(raw_items)
    names = [it.item_name for it in sorted_res]

    # 1. 验证第1标段全部聚合在第2标段之前
    assert names[0] == "标的物A（第1标段）"
    assert names[1] == "标的物B（第1标段）"
    assert names[2] == "标的物C（第2标段）"
    assert names[3] == "标的物D（第2标段）"


def test_sort_cost_items_prefers_frontend_sort_order_when_present():
    """已迁移 BOM 必须保持前端原始顺序，不能再次按区域/标段重排。"""
    from app.agents.tools.bid_db_tools import sort_cost_items_by_scope_and_hierarchy
    from types import SimpleNamespace

    raw_items = [
        SimpleNamespace(item_name="后显示项", sort_order=1),
        SimpleNamespace(item_name="前显示项", sort_order=0),
    ]

    sorted_res = sort_cost_items_by_scope_and_hierarchy(raw_items)
    assert [item.item_name for item in sorted_res] == ["前显示项", "后显示项"]


def test_sort_cost_items_clusters_scopes_but_keeps_frontend_order_inside_scope():
    """多区域时先聚类，区域内仍按前端 sort_order 排列。"""
    from app.agents.tools.bid_db_tools import sort_cost_items_by_scope_and_hierarchy
    from types import SimpleNamespace

    raw_items = [
        SimpleNamespace(item_name="区域二-后项（第2标段）", sort_order=3),
        SimpleNamespace(item_name="区域一-后项（第1标段）", sort_order=2),
        SimpleNamespace(item_name="区域二-前项（第2标段）", sort_order=1),
        SimpleNamespace(item_name="区域一-前项（第1标段）", sort_order=0),
    ]

    sorted_res = sort_cost_items_by_scope_and_hierarchy(raw_items)
    assert [item.item_name for item in sorted_res] == [
        "区域一-前项（第1标段）",
        "区域一-后项（第1标段）",
        "区域二-前项（第2标段）",
        "区域二-后项（第2标段）",
    ]


def test_build_dynamic_matrix_for_header_with_auto_clustering():
    """测试 build_dynamic_matrix_for_header 自动聚类排序、分部标题行与小计行生成"""
    from app.agents.tools.bid_db_tools import build_dynamic_matrix_for_header
    from types import SimpleNamespace

    raw_items = [
        SimpleNamespace(item_name="标的物B（二区）", brand="品牌B", spec="规格B", unit="项", quantity=1, unit_price=200, calculated_total=200, remark=""),
        SimpleNamespace(item_name="标的物A（一区）", brand="品牌A", spec="规格A\n带换行", unit="项", quantity=2, unit_price=100, calculated_total=200, remark=""),
    ]

    header_cols = ["__INDEX__", "item_name", "__BRAND_SPEC__", "unit", "quantity", "unit_price", "calculated_total"]
    matrix = build_dynamic_matrix_for_header(raw_items, header_cols)

    # 多区域时应生成：一区标题行、1.1明细行、一区小计行、二区标题行、2.1明细行、二区小计行（共 6 行）
    assert len(matrix) == 6

    # 1. 验证一区标题行与明细
    assert matrix[0][0] == "一、"
    assert "一区" in matrix[0][1]
    assert matrix[1][0] == "1.1"
    assert "标的物A" in matrix[1][1]
    assert matrix[1][2] == "品牌A 规格A 带换行"
    assert "一区 小计" in matrix[2][1]

    # 2. 验证二区标题行与明细
    assert matrix[3][0] == "二、"
    assert "二区" in matrix[3][1]
    assert matrix[4][0] == "2.1"
    assert "标的物B" in matrix[4][1]
    assert "二区 小计" in matrix[5][1]


def test_build_dynamic_matrix_manufacturer_support():
    """测试 build_dynamic_matrix_for_header 对生产厂家的全链路支持与多级回溯解析"""
    from app.agents.tools.bid_db_tools import build_dynamic_matrix_for_header
    from types import SimpleNamespace

    raw_items = [
        # 1. 显式包含 manufacturer
        SimpleNamespace(item_name="光伏组件", brand="隆基绿能", manufacturer="隆基乐叶光伏科技有限公司", spec="LR5-72HBD-550M", unit="块", quantity=800, unit_price=650.0, calculated_total=520000.0, remark=""),
        # 2. manufacturer 为空但包含 brand，应回溯使用 brand 作为生产厂家
        SimpleNamespace(item_name="组串式逆变器", brand="华为技术", manufacturer="", spec="SUN2000-110KTL-M2", unit="台", quantity=4, unit_price=25000.0, calculated_total=100000.0, remark=""),
    ]

    # 测试场景 1: 使用英文 ORM 字段名 'manufacturer'
    header_cols_en = ["__INDEX__", "item_name", "spec", "manufacturer", "unit", "quantity", "unit_price", "calculated_total"]
    matrix_en = build_dynamic_matrix_for_header(raw_items, header_cols_en)
    assert len(matrix_en) == 2
    assert matrix_en[0][3] == "隆基乐叶光伏科技有限公司"
    assert matrix_en[1][3] == "华为技术"  # 回溯回退为 brand

    # 测试场景 2: 使用中文表头名 '生产厂家'
    header_cols_cn = ["序号", "货物名称", "规格型号", "生产厂家", "单位", "数量", "单价", "合价"]
    matrix_cn = build_dynamic_matrix_for_header(raw_items, header_cols_cn)
    assert len(matrix_cn) == 2
    assert matrix_cn[0][3] == "隆基乐叶光伏科技有限公司"
    assert matrix_cn[1][3] == "华为技术"


def test_build_dynamic_matrix_brand_spec_dedup_and_formatting():
    """测试 build_dynamic_matrix_for_header 对【品牌、规格、型号】合并列的智能格式化与去重"""
    from app.agents.tools.bid_db_tools import build_dynamic_matrix_for_header
    from types import SimpleNamespace

    raw_items = [
        # 1. 品牌独立，规格独立
        SimpleNamespace(item_name="光伏组件", brand="天合光能", manufacturer="天合光能股份有限公司", spec="TSM-DEG21C.20 635Wp", unit="块", quantity=763, unit_price=882.69, calculated_total=673492.47, remark=""),
        # 2. 规格字符串开头已包含品牌名，避免拼接为 '华为 华为 SUN2000-110KTL'
        SimpleNamespace(item_name="组串式逆变器", brand="华为", manufacturer="华为技术有限公司", spec="华为 SUN2000-110KTL (110kW)", unit="台", quantity=6, unit_price=11555.0, calculated_total=69330.0, remark=""),
        # 3. 只有规格，品牌为空
        SimpleNamespace(item_name="彩钢瓦", brand="", manufacturer="东方钢构", spec="0.5mm厚 热镀锌", unit="平方米", quantity=3200, unit_price=25.14, calculated_total=80448.0, remark=""),
    ]

    header_cols = ["__INDEX__", "item_name", "__BRAND_SPEC__", "manufacturer", "unit", "quantity", "unit_price", "calculated_total"]
    matrix = build_dynamic_matrix_for_header(raw_items, header_cols)
    assert len(matrix) == 3
    assert matrix[0][2] == "天合光能 TSM-DEG21C.20 635Wp"
    assert matrix[1][2] == "华为 SUN2000-110KTL (110kW)"  # 自动去重
    assert matrix[2][2] == "0.5mm厚 热镀锌"
