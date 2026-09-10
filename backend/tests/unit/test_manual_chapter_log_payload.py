"""人工撰写待办审计日志载荷测试。"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.api.endpoints.bid_generator import _extract_manual_chapters_from_logs
from app.services.bid_template_service import BidTemplateService


def test_extract_manual_chapters_from_latest_audit_log_should_return_manual_items() -> None:
    """应从最新一条带人工章节载荷的审计日志中读取待办。"""
    manual_item = {
        "chapter_number": "六",
        "chapter_title": "技术方案",
        "content_hint": "请人工补充项目实施方案",
        "template_text": "技术方案：",
        "status": "manual_pending",
    }
    logs = [
        SimpleNamespace(outputs={"manual_chapters": [manual_item]}),
        SimpleNamespace(outputs={"manual_chapters": []}),
    ]

    assert _extract_manual_chapters_from_logs(logs) == [manual_item]


def test_extract_manual_chapters_from_logs_without_payload_should_return_empty_list() -> None:
    """历史日志没有人工待办载荷时应安全返回空列表。"""
    logs = [SimpleNamespace(outputs={"summary": "旧日志"}), SimpleNamespace(outputs=None)]

    assert _extract_manual_chapters_from_logs(logs) == []


def test_get_binding_should_filter_active_tenant_binding() -> None:
    """查询绑定关系时必须按文档、租户和 active 状态过滤。"""
    expected_binding = SimpleNamespace(id="binding-1", template_id="template-1")
    query = MagicMock()
    query.filter.return_value.first.return_value = expected_binding
    db = MagicMock()
    db.query.return_value = query

    result = BidTemplateService().get_binding(db, "document-1", "tenant-1")

    assert result is expected_binding
    query.filter.assert_called_once()
