from types import SimpleNamespace
from unittest.mock import patch

from app.services.metadata.engineering_service import EngineeringSchema, EquipmentItem
from app.agents.tools.metadata_tools import extract_engineering_info


def test_extract_engineering_info_should_use_system_document_query_for_full_context():
    """工程提取应使用系统查询拿到完整上下文，避免错误降级到 RAG。"""
    fake_db = SimpleNamespace(close=lambda: None)
    fake_doc = SimpleNamespace(parsed_metadata={})
    fake_chunks = [SimpleNamespace(content="<table><tr><td>设备A</td></tr></table>")]
    fake_result = EngineeringSchema(
        main_equipment_list=[EquipmentItem(item_name="设备A")]
    )

    with patch("app.agents.tools.security.validate_document_access", return_value=True), \
         patch("app.db.session.SessionLocal", return_value=fake_db), \
         patch("app.db.crud.document.document_crud.get_document_by_id_system", return_value=fake_doc) as system_query, \
         patch("app.db.crud.document.document_crud.get_document_chunks", return_value=fake_chunks), \
         patch("app.services.metadata.engineering_service.engineering_service.extract_metadata", return_value=fake_result) as extract_mock, \
         patch("app.worker.tasks.emit_agent_log"):
        result = extract_engineering_info.invoke({"document_id": "document-a"})

    system_query.assert_called_once_with(fake_db, "document-a")
    extract_mock.assert_called_once()
    assert "设备A" in result
