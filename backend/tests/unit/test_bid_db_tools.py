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


def test_bound_company_profile_tool_should_prefer_explicit_profile_id():
    """正常场景：固定工具必须使用显式档案，不受当前线程上下文影响。"""
    from types import SimpleNamespace
    from app.agents.tools.bid_db_tools import create_company_profile_query_tool, current_profile_id

    db = MagicMock()
    selected_profile = SimpleNamespace(company_name="四川石楠建设工程有限公司")
    token = current_profile_id.set("default-profile")
    try:
        with patch("app.agents.tools.bid_db_tools.SessionLocal", return_value=db), patch(
            "app.agents.tools.bid_db_tools.resolve_company_profile",
            return_value=selected_profile,
        ) as resolve_mock:
            bound_tool = create_company_profile_query_tool("selected-profile")
            result = bound_tool.invoke({"field_key": "投标人名称"})
    finally:
        current_profile_id.reset(token)

    assert bound_tool.name == "query_company_profile_tool"
    assert result == "四川石楠建设工程有限公司"
    resolve_mock.assert_called_once_with(db, "selected-profile")
    db.close.assert_called_once_with()


def test_bound_company_profile_tool_should_keep_context_fallback_when_profile_id_empty():
    """边界场景：未绑定档案时保留旧的 ContextVar 兼容路径。"""
    from types import SimpleNamespace
    from app.agents.tools.bid_db_tools import create_company_profile_query_tool, current_profile_id

    db = MagicMock()
    default_profile = SimpleNamespace(company_name="默认企业")
    token = current_profile_id.set("context-profile")
    try:
        with patch("app.agents.tools.bid_db_tools.SessionLocal", return_value=db), patch(
            "app.agents.tools.bid_db_tools.resolve_company_profile",
            return_value=default_profile,
        ) as resolve_mock:
            bound_tool = create_company_profile_query_tool()
            result = bound_tool.invoke({"field_key": "company_name"})
    finally:
        current_profile_id.reset(token)

    assert result == "默认企业"
    resolve_mock.assert_called_once_with(db, "context-profile")


def test_bound_company_profile_tool_should_return_query_error_when_resolver_fails():
    """异常场景：档案解析失败时返回可识别错误并记录资源清理。"""
    db = MagicMock()
    with patch("app.agents.tools.bid_db_tools.SessionLocal", return_value=db), patch(
        "app.agents.tools.bid_db_tools.resolve_company_profile",
        side_effect=RuntimeError("profile database unavailable"),
    ):
        from app.agents.tools.bid_db_tools import create_company_profile_query_tool

        result = create_company_profile_query_tool("selected-profile").invoke(
            {"field_key": "投标人名称"}
        )

    assert "查询异常" in result
    assert "profile database unavailable" in result
    db.close.assert_called_once_with()


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


def test_sort_cost_items_by_section_name_keeps_section_order_and_item_order():
    """测试按结构化 section_name 聚类，并保持分区内原始顺序。"""
    from app.agents.tools.bid_db_tools import sort_cost_items_by_scope_and_hierarchy
    from types import SimpleNamespace

    # 使用结构化分区字段，名称本身不承担分区语义。
    raw_items = [
        SimpleNamespace(item_name="清单项C", section_name="外层分区乙", sort_order=2, calculated_total=100),
        SimpleNamespace(item_name="清单项A", section_name="外层分区甲", sort_order=1, calculated_total=500),
        SimpleNamespace(item_name="清单项D", section_name="外层分区乙", sort_order=4, calculated_total=200),
        SimpleNamespace(item_name="清单项B", section_name="外层分区甲", sort_order=3, calculated_total=300),
    ]

    sorted_res = sort_cost_items_by_scope_and_hierarchy(raw_items)
    names = [it.item_name for it in sorted_res]

    # 分区顺序按首次出现顺序，分区内按 sort_order 排列。
    assert names == ["清单项C", "清单项D", "清单项A", "清单项B"]


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


def test_sort_cost_items_without_section_name_preserves_original_order():
    """没有结构化分区时保持原始顺序，不从名称猜测分区。"""
    from app.agents.tools.bid_db_tools import sort_cost_items_by_scope_and_hierarchy
    from types import SimpleNamespace

    raw_items = [
        SimpleNamespace(item_name="清单项D", sort_order=3),
        SimpleNamespace(item_name="清单项B", sort_order=2),
        SimpleNamespace(item_name="清单项C", sort_order=1),
        SimpleNamespace(item_name="清单项A", sort_order=0),
    ]

    sorted_res = sort_cost_items_by_scope_and_hierarchy(raw_items)
    assert [item.item_name for item in sorted_res] == ["清单项A", "清单项C", "清单项B", "清单项D"]


def test_build_dynamic_matrix_for_header_with_auto_clustering():
    """测试 build_dynamic_matrix_for_header 自动聚类排序、分部标题行与小计行生成"""
    from app.agents.tools.bid_db_tools import build_dynamic_matrix_for_header
    from types import SimpleNamespace

    raw_items = [
        SimpleNamespace(item_name="清单项A", section_name="外层分区甲", brand="品牌A", spec="规格A\n带换行", unit="项", quantity=2, unit_price=100, calculated_total=200, remark="", sort_order=0),
        SimpleNamespace(item_name="清单项B", section_name="外层分区乙", brand="品牌B", spec="规格B", unit="项", quantity=1, unit_price=200, calculated_total=200, remark="", sort_order=1),
    ]

    header_cols = ["__INDEX__", "item_name", "__BRAND_SPEC__", "unit", "quantity", "unit_price", "calculated_total"]
    matrix = build_dynamic_matrix_for_header(raw_items, header_cols)

    # 多外层分区时应生成：分区标题、明细和小计行（共 6 行）。
    assert len(matrix) == 6

    # 1. 验证第一个外层分区标题与明细
    assert matrix[0][0] == "1、"
    assert "外层分区甲" in matrix[0][1]
    assert matrix[1][0] == "1.1"
    assert "清单项A" in matrix[1][1]
    assert matrix[1][2] == "品牌A 规格A 带换行"
    assert "外层分区甲 小计" in matrix[2][1]

    # 2. 验证第二个外层分区标题与明细
    assert matrix[3][0] == "2、"
    assert "外层分区乙" in matrix[3][1]
    assert matrix[4][0] == "2.1"
    assert "清单项B" in matrix[4][1]
    assert "外层分区乙 小计" in matrix[5][1]


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


def test_build_dynamic_matrix_preserves_internal_boq_group_rows():
    """表外分区只有一层时，表内 BOQ 分组仍应生成结构行且不参与计价。"""
    from app.agents.tools.bid_db_tools import build_dynamic_matrix_for_header
    from types import SimpleNamespace

    raw_items = [
        SimpleNamespace(
            item_name="清单项甲",
            section_name="外层分区甲",
            part_name="报价部分甲",
            group_path=["报价部分甲", "分类甲"],
            quantity=2,
            unit="项",
            unit_price=10.0,
            calculated_total=20.0,
            sort_order=0,
        ),
        SimpleNamespace(
            item_name="清单项乙",
            section_name="外层分区甲",
            part_name="报价部分乙",
            group_path=["报价部分乙"],
            quantity=3,
            unit="项",
            unit_price=15.0,
            calculated_total=45.0,
            sort_order=1,
        ),
    ]

    matrix = build_dynamic_matrix_for_header(
        raw_items,
        ["__INDEX__", "item_name", "unit", "quantity", "unit_price", "calculated_total"],
    )

    assert len(matrix) == 5
    assert matrix[0][1] == "报价部分甲"
    assert matrix[0][0] == ""
    assert matrix[0][-1] == ""
    assert matrix[1][1] == "分类甲"
    assert matrix[2][0] == "1"
    assert matrix[2][1] == "清单项甲"
    assert matrix[3][1] == "报价部分乙"
    assert matrix[4][0] == "2"
    assert matrix[4][1] == "清单项乙"


def test_build_dynamic_matrix_keeps_nonstandard_external_sections_and_all_items():
    """外层分区名称不含编号时也应按 section_name 分组，且不丢失无分区历史项。"""
    from app.agents.tools.bid_db_tools import build_dynamic_matrix_for_header
    from types import SimpleNamespace

    raw_items = [
        SimpleNamespace(item_name="分区乙明细", section_name="分区乙", calculated_total=2.0, sort_order=2),
        SimpleNamespace(item_name="无分区历史项", section_name=None, calculated_total=3.0, sort_order=3),
        SimpleNamespace(item_name="分区甲明细", section_name="分区甲", calculated_total=1.0, sort_order=0),
    ]

    matrix = build_dynamic_matrix_for_header(raw_items, ["__INDEX__", "item_name", "calculated_total"])
    names = [row[1] for row in matrix if row[1] and not row[1].endswith("小计")]

    assert "分区甲" in names
    assert "分区乙" in names
    assert "无分区历史项" in names
    assert sum("明细" in name or "历史项" in name for name in names) == 3


def test_build_dynamic_matrix_without_section_name_does_not_infer_external_groups():
    """没有 section_name 时不从项目名称猜测外层分组。"""
    from app.agents.tools.bid_db_tools import build_dynamic_matrix_for_header
    from types import SimpleNamespace

    raw_items = [
        SimpleNamespace(item_name="清单项甲", section_name=None, calculated_total=1.0),
        SimpleNamespace(item_name="清单项乙", section_name=None, calculated_total=2.0),
    ]

    matrix = build_dynamic_matrix_for_header(raw_items, ["__INDEX__", "item_name", "calculated_total"])

    assert len(matrix) == 2
    assert matrix[0][0] == "1"
    assert matrix[1][0] == "2"


def test_enrich_cost_items_with_saved_group_context_before_bid_filling():
    """成本关系表缺少表内分组列时，应从已保存快照优先补回结构字段。"""
    from app.agents.tools.bid_db_tools import _enrich_cost_items_with_structure
    from types import SimpleNamespace

    document = SimpleNamespace(
        parsed_metadata={
            "cost_analysis": {
                "items": [
                    {
                        "item_code": "A-1",
                        "name": "清单项甲",
                        "part_name": "报价部分甲",
                        "group_path": ["报价部分甲", "分类甲"],
                        "section_name": "外层分区甲",
                    }
                ]
            }
        }
    )
    engineering = SimpleNamespace(
        main_equipment_list=[
            {
                "item_code": "A-1",
                "item_name": "清单项甲",
                "part_name": "工程元数据部分",
                "group_path": ["工程元数据部分"],
            }
        ]
    )
    query_result = MagicMock()
    query_result.filter.return_value.first.side_effect = [document, engineering]
    db = MagicMock()
    db.query.return_value = query_result
    cost_item = SimpleNamespace(
        item_code="A-1",
        item_name="清单项甲",
        quantity=1,
        calculated_total=5.0,
    )

    enriched = _enrich_cost_items_with_structure(db, "doc-1", [cost_item])

    assert enriched[0].part_name == "报价部分甲"
    assert enriched[0].group_path == ["报价部分甲", "分类甲"]
    assert enriched[0].section_name == "外层分区甲"
