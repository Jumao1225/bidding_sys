from unittest.mock import patch

from app.services.metadata.engineering_service import EngineeringSchema, EquipmentItem
from app.agents.tools.metadata_tools import extract_engineering_info
from app.services.routing_service import RoutingDecision


def test_extract_engineering_info_should_use_vector_retrieval_context():
    """工程提取应先召回，并在完整章节不可用时保留召回上下文。"""
    retrieved_context = "<table><tr><td>设备A</td></tr></table>"
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
    """工程清单应直接使用 RAG 按 section_title 扩展后的完整章节上下文。"""
    fake_result = EngineeringSchema(
        main_equipment_list=[EquipmentItem(item_name="设备B")]
    )
    with patch("app.agents.tools.security.validate_document_access", return_value=True), \
         patch("app.agents.tools.metadata_tools.rag_service.search_bidding_document", return_value="完整章节原文") as rag_search, \
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
    extract_mock.assert_called_once_with("完整章节原文", "document-b", tenant_id=None)


def test_extract_engineering_info_should_pass_multiple_routed_chapters_to_rag():
    """路由返回多个章节时，应将章节限定交给数据库章节召回。"""
    fake_result = EngineeringSchema(
        main_equipment_list=[EquipmentItem(item_name="设备C")]
    )

    with patch("app.agents.tools.security.validate_document_access", return_value=True), \
         patch(
             "app.agents.tools.metadata_tools.routing_service.analyze_intent_and_route",
             return_value=RoutingDecision(
                 is_global_search=False,
                 target_chapters=["章节一", "章节二"],
             ),
         ), \
         patch("app.agents.tools.metadata_tools.rag_service.search_bidding_document", return_value="召回片段") as rag_search, \
         patch("app.services.metadata.engineering_service.engineering_service.extract_metadata", return_value=fake_result) as extract_mock, \
         patch("app.worker.tasks.emit_agent_log"):
        extract_engineering_info.invoke({
            "document_id": "document-c",
            "search_keywords": "设备规格数量",
        })

    rag_search.assert_called_once_with(
        document_id="document-c",
        query="设备规格数量",
        section_title=["章节一", "章节二"],
        top_k=5,
        context_mode="chapter",
        query_mode="split",
    )
    extract_mock.assert_called_once_with("召回片段", "document-c", tenant_id=None)


def test_extract_engineering_info_should_discover_table_chapters_when_routing_is_global():
    """路由未锁定章节时，应根据当前文档表格分块补取完整章节。"""
    fake_result = EngineeringSchema(
        main_equipment_list=[EquipmentItem(item_name="设备D")]
    )

    with patch("app.agents.tools.security.validate_document_access", return_value=True), \
         patch(
             "app.agents.tools.metadata_tools.routing_service.analyze_intent_and_route",
             return_value=RoutingDecision(is_global_search=True, target_chapters=[]),
         ), \
         patch(
             "app.agents.tools.metadata_tools._discover_table_chapter_titles",
             return_value=["文档中的表格章节"],
         ) as discover_chapters, \
         patch("app.agents.tools.metadata_tools.rag_service.search_bidding_document", return_value="召回片段"), \
         patch("app.services.metadata.engineering_service.engineering_service.extract_metadata", return_value=fake_result) as extract_mock, \
         patch("app.worker.tasks.emit_agent_log"):
        extract_engineering_info.invoke({
            "document_id": "document-d",
            "search_keywords": "设备规格数量",
        })

    discover_chapters.assert_called_once_with("document-d", "设备规格数量", None)
    extract_mock.assert_called_once_with("召回片段", "document-d", tenant_id=None)
