from unittest.mock import patch

from app.services.metadata.engineering_service import EngineeringSchema, EquipmentItem
from app.agents.tools.metadata_tools import (
    _score_engineering_table_shape,
    extract_engineering_info,
)
from app.services.routing_service import RoutingDecision


def test_extract_engineering_info_should_use_vector_retrieval_context():
    """工程提取应优先使用 RAG 返回的结构化上下文。"""
    retrieved_context = "<table><tr><th>名称</th></tr><tr><td>设备A</td></tr></table>"
    fake_result = EngineeringSchema(
        main_equipment_list=[EquipmentItem(item_name="设备A")]
    )

    with patch("app.agents.tools.security.validate_document_access", return_value=True), \
         patch("app.agents.tools.metadata_tools.rag_service.search_bidding_document", return_value=retrieved_context) as rag_search, \
         patch("app.agents.tools.metadata_tools.rag_service.get_full_chapter_text", return_value="错误：章节不存在"), \
         patch("app.services.metadata.engineering_service.engineering_service.extract_metadata", return_value=fake_result) as extract_mock, \
         patch("app.worker.tasks.emit_agent_log"):
        result = extract_engineering_info.invoke({
            "document_id": "document-a",
            "search_keywords": "设备规格数量",
            "section_title": "测试章节",
        })

    rag_search.assert_called_once_with(
        document_id="document-a",
        query="设备规格数量",
        section_title="测试章节",
        top_k=5,
        context_mode="chapter",
        query_mode="split",
    )
    extract_mock.assert_called_once_with(retrieved_context, "document-a", tenant_id=None)
    assert "设备A" in result


def test_extract_engineering_info_should_keep_database_chapter_context():
    """工程清单应保留 RAG 按 section_title 扩展后的完整章节上下文。"""
    fake_result = EngineeringSchema(
        main_equipment_list=[EquipmentItem(item_name="设备B")]
    )
    with patch("app.agents.tools.security.validate_document_access", return_value=True), \
         patch("app.agents.tools.metadata_tools.rag_service.search_bidding_document", return_value="<table><tr><th>名称</th></tr><tr><td>设备B</td></tr></table>") as rag_search, \
         patch("app.agents.tools.metadata_tools.rag_service.get_full_chapter_text") as full_chapter, \
         patch("app.services.metadata.engineering_service.engineering_service.extract_metadata", return_value=fake_result) as extract_mock, \
         patch("app.worker.tasks.emit_agent_log"):
        extract_engineering_info.invoke({
            "document_id": "document-b",
            "search_keywords": "设备规格数量",
            "section_title": "第四章项目需求",
        })

    rag_search.assert_called_once()
    full_chapter.assert_not_called()
    extract_mock.assert_called_once_with(
        "<table><tr><th>名称</th></tr><tr><td>设备B</td></tr></table>",
        "document-b",
        tenant_id=None,
    )


def test_extract_engineering_info_should_use_direct_tables_before_rag():
    """未指定章节时，工程清单应优先直接读取候选表格。"""
    fake_result = EngineeringSchema(
        main_equipment_list=[EquipmentItem(item_name="设备C")]
    )

    with patch("app.agents.tools.security.validate_document_access", return_value=True), \
         patch(
             "app.agents.tools.metadata_tools.routing_service.analyze_intent_and_route",
         ) as route, \
         patch(
             "app.agents.tools.metadata_tools._discover_table_chapter_titles",
             return_value=["真实清单章节"],
         ) as discover_chapters, \
         patch("app.agents.tools.metadata_tools._load_engineering_table_context", return_value="直接表格原文") as table_context, \
         patch(
             "app.agents.tools.metadata_tools.rag_service.search_bidding_document",
         ) as rag_search, \
         patch("app.services.metadata.engineering_service.engineering_service.extract_metadata", return_value=fake_result) as extract_mock, \
         patch("app.worker.tasks.emit_agent_log"):
        extract_engineering_info.invoke({
            "document_id": "document-c",
            "search_keywords": "设备规格数量",
        })

    route.assert_not_called()
    discover_chapters.assert_called_once_with("document-c", "设备规格数量", None)
    table_context.assert_called_once_with(
        document_id="document-c",
        section_title=["真实清单章节"],
        tenant_id=None,
    )
    rag_search.assert_not_called()
    extract_mock.assert_called_once_with("直接表格原文", "document-c", tenant_id=None)


def test_extract_engineering_info_should_fallback_to_rag_when_direct_tables_unavailable():
    """候选表格直接读取无结果时，工程清单应回退到 RAG。"""
    fake_result = EngineeringSchema(
        main_equipment_list=[EquipmentItem(item_name="设备F")]
    )

    with patch("app.agents.tools.security.validate_document_access", return_value=True), \
         patch(
             "app.agents.tools.metadata_tools._discover_table_chapter_titles",
             return_value=["文档中的表格章节"],
         ), \
         patch(
             "app.agents.tools.metadata_tools.rag_service.search_bidding_document",
             return_value="RAG 表格原文",
         ) as rag_search, \
         patch(
             "app.agents.tools.metadata_tools._load_engineering_table_context",
             return_value="",
         ) as table_context, \
         patch(
             "app.services.metadata.engineering_service.engineering_service.extract_metadata",
             return_value=fake_result,
         ) as extract_mock, \
         patch("app.worker.tasks.emit_agent_log"):
        extract_engineering_info.invoke({
            "document_id": "document-f",
            "search_keywords": "设备规格数量",
        })

    rag_search.assert_called_once()
    table_context.assert_called_once_with(
        document_id="document-f",
        section_title=["文档中的表格章节"],
        tenant_id=None,
    )
    extract_mock.assert_called_once_with("RAG 表格原文", "document-f", tenant_id=None)


def test_score_engineering_table_shape_should_accept_unknown_headers():
    """陌生表头只要具备清单数据分布，也应被识别为候选表格。"""
    table_content = """
    <table>
      <tr><th>列甲</th><th>列乙</th><th>列丙</th><th>列丁</th></tr>
      <tr><td>行A</td><td>描述内容A超过长度阈值</td><td>单位A</td><td>10</td></tr>
      <tr><td>行B</td><td>描述内容B超过长度阈值</td><td>单位A</td><td>20</td></tr>
    </table>
    """

    assert _score_engineering_table_shape(table_content) > 0


def test_score_engineering_table_shape_should_reject_non_measurement_tables():
    """只有编号或费率数值、缺少清单数据分布的表格不应成为候选。"""
    serial_table = """
    <table>
      <tr><th>列甲</th><th>列乙</th><th>列丙</th></tr>
      <tr><td>1</td><td>内容A</td><td>内容B</td></tr>
      <tr><td>2</td><td>内容C</td><td>内容D</td></tr>
    </table>
    """
    rate_table = """
    <table>
      <tr><th>列甲</th><th>列乙</th><th>列丙</th><th>列丁</th></tr>
      <tr><td>区间A</td><td>1</td><td>2</td><td>3</td></tr>
      <tr><td>区间B</td><td>4</td><td>5</td><td>6</td></tr>
    </table>
    """

    assert _score_engineering_table_shape(serial_table) == 0
    assert _score_engineering_table_shape(rate_table) == 0


def test_extract_engineering_info_should_keep_explicit_chapter_limit():
    """用户明确指定章节时，工程清单仍应保留章节限定。"""
    fake_result = EngineeringSchema(
        main_equipment_list=[EquipmentItem(item_name="设备E")]
    )

    with patch("app.agents.tools.security.validate_document_access", return_value=True), \
         patch("app.agents.tools.metadata_tools.routing_service.analyze_intent_and_route") as route, \
         patch("app.agents.tools.metadata_tools._discover_table_chapter_titles") as discover_chapters, \
         patch("app.agents.tools.metadata_tools.rag_service.search_bidding_document", return_value="<table><tr><th>名称</th></tr><tr><td>设备E</td></tr></table>") as rag_search, \
         patch("app.services.metadata.engineering_service.engineering_service.extract_metadata", return_value=fake_result), \
         patch("app.worker.tasks.emit_agent_log"):
        extract_engineering_info.invoke({
            "document_id": "document-e",
            "search_keywords": "设备规格数量",
            "section_title": "用户指定章节",
        })

    route.assert_not_called()
    discover_chapters.assert_not_called()
    rag_search.assert_called_once_with(
        document_id="document-e",
        query="设备规格数量",
        section_title="用户指定章节",
        top_k=5,
        context_mode="chapter",
        query_mode="split",
    )


def test_extract_engineering_info_should_use_direct_tables_when_routing_is_global():
    """自动工程清单提取应跳过通用路由后优先直接读取候选表格。"""
    fake_result = EngineeringSchema(
        main_equipment_list=[EquipmentItem(item_name="设备D")]
    )

    with patch("app.agents.tools.security.validate_document_access", return_value=True), \
         patch(
             "app.agents.tools.metadata_tools.routing_service.analyze_intent_and_route",
             return_value=RoutingDecision(is_global_search=True, target_chapters=[]),
         ) as route, \
         patch(
             "app.agents.tools.metadata_tools._discover_table_chapter_titles",
             return_value=["文档中的表格章节"],
         ) as discover_chapters, \
         patch("app.agents.tools.metadata_tools._load_engineering_table_context", return_value="直接表格片段") as table_context, \
         patch(
             "app.agents.tools.metadata_tools.rag_service.search_bidding_document",
         ) as rag_search, \
         patch("app.services.metadata.engineering_service.engineering_service.extract_metadata", return_value=fake_result) as extract_mock, \
         patch("app.worker.tasks.emit_agent_log"):
        extract_engineering_info.invoke({
            "document_id": "document-d",
            "search_keywords": "设备规格数量",
        })

    route.assert_not_called()
    discover_chapters.assert_called_once_with("document-d", "设备规格数量", None)
    table_context.assert_called_once_with(
        document_id="document-d",
        section_title=["文档中的表格章节"],
        tenant_id=None,
    )
    rag_search.assert_not_called()
    extract_mock.assert_called_once_with("直接表格片段", "document-d", tenant_id=None)
