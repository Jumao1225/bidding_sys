"""测试前台数据库工具适配层，确保不会产生嵌套 LangChain 工具事件。"""

from unittest.mock import MagicMock, patch

from app.agents.tools import chat_db_tools


def _build_raw_tool_mock(result: str = "综合评估法") -> MagicMock:
    """创建带有原始函数入口的模拟 StructuredTool。"""
    raw_tool = MagicMock()
    raw_tool.name = "query_evaluation_method_tool"
    raw_tool.func = MagicMock(return_value=result)
    raw_tool.invoke = MagicMock(side_effect=AssertionError("不应再次触发嵌套工具事件"))
    return raw_tool


def test_safe_document_tool_call_authorized_should_call_raw_function_once() -> None:
    """正常场景：文档有权限时只调用原始函数，不触发嵌套 invoke。"""
    raw_tool = _build_raw_tool_mock()

    with patch.object(chat_db_tools, "validate_document_access", return_value=True):
        result = chat_db_tools._safe_document_tool_call(
            raw_tool,
            "document-1",
            {"document_id": "document-1", "detail_type": "method"},
        )

    assert result == "综合评估法"
    raw_tool.func.assert_called_once_with(document_id="document-1", detail_type="method")
    raw_tool.invoke.assert_not_called()


def test_safe_document_tool_call_function_error_should_return_database_error() -> None:
    """异常场景：原始查询函数失败时返回统一的数据库查询异常信息。"""
    raw_tool = _build_raw_tool_mock()
    raw_tool.func = MagicMock(side_effect=RuntimeError("数据库连接失败"))

    with patch.object(chat_db_tools, "validate_document_access", return_value=True):
        result = chat_db_tools._safe_document_tool_call(
            raw_tool,
            "document-1",
            {"document_id": "document-1", "detail_type": "method"},
        )

    assert result == "[数据库查询异常: 数据库连接失败]"
    raw_tool.func.assert_called_once()
    raw_tool.invoke.assert_not_called()


def test_safe_document_tool_call_unauthorized_should_reject_without_query() -> None:
    """边界场景：无权访问文档时直接拒绝，不能调用任何数据库函数。"""
    raw_tool = _build_raw_tool_mock()

    with patch.object(chat_db_tools, "validate_document_access", return_value=False):
        result = chat_db_tools._safe_document_tool_call(
            raw_tool,
            "document-1",
            {"document_id": "document-1", "detail_type": "method"},
        )

    assert result == "[无权访问当前文档]"
    raw_tool.func.assert_not_called()
    raw_tool.invoke.assert_not_called()


def test_query_evaluation_method_tool_should_bypass_nested_invoke() -> None:
    """集成适配场景：评标办法工具只经过一层 LangChain 工具包装。"""
    raw_tool = _build_raw_tool_mock("综合评估法 (总分: 100.0分)")

    with patch.object(chat_db_tools, "_query_evaluation_method_tool", raw_tool), patch.object(
        chat_db_tools, "validate_document_access", return_value=True
    ):
        result = chat_db_tools.query_evaluation_method_tool.invoke(
            {"document_id": "document-1", "detail_type": "method"}
        )

    assert result == "综合评估法 (总分: 100.0分)"
    raw_tool.func.assert_called_once_with(document_id="document-1", detail_type="method")
    raw_tool.invoke.assert_not_called()
