"""标书撰写日志查询的并发隔离测试。"""

from unittest.mock import patch

from app.api.endpoints.bid_generator import (
    _get_first_bid_fill_duration_ms,
    _persist_first_bid_fill_duration,
    _query_bid_fill_logs,
)


class FakeQuery:
    """用于验证查询降级分支的链式查询替身。"""

    def __init__(self, logs: list[object], fail_filter: bool = False) -> None:
        self.logs = logs
        self.fail_filter = fail_filter

    def filter(self, *_args: object) -> "FakeQuery":
        """模拟首选条件查询。"""
        if self.fail_filter:
            raise RuntimeError("模拟 JSON 条件过滤失败")
        return self

    def order_by(self, *_args: object) -> "FakeQuery":
        """模拟排序查询。"""
        return self

    def limit(self, _count: int) -> "FakeQuery":
        """模拟历史日志数量限制。"""
        return self

    def all(self) -> list[object]:
        """返回预设日志。"""
        return self.logs


class FakeSession:
    """记录日志查询是否在独立会话中完成并及时释放。"""

    def __init__(self, logs: list[object], fail_filter: bool = False) -> None:
        self.query_obj = FakeQuery(logs, fail_filter=fail_filter)
        self.closed = False

    def query(self, *_args: object) -> FakeQuery:
        """返回查询替身。"""
        return self.query_obj

    def close(self) -> None:
        """记录会话关闭。"""
        self.closed = True


class FakeDocumentQuery:
    """用于模拟文档元数据查询的链式查询替身。"""

    def __init__(self, document: object | None) -> None:
        self.document = document

    def filter(self, *_args: object) -> "FakeDocumentQuery":
        """忽略 SQL 条件并返回当前查询替身。"""
        return self

    def first(self) -> object | None:
        """返回预设文档。"""
        return self.document


class FakeDocumentSession:
    """记录首次耗时元数据的读取、提交与回滚行为。"""

    def __init__(self, document: object | None) -> None:
        self.document_query = FakeDocumentQuery(document)
        self.commit_count = 0
        self.rollback_count = 0

    def query(self, *_args: object) -> FakeDocumentQuery:
        """返回文档查询替身。"""
        return self.document_query

    def commit(self) -> None:
        """记录提交动作。"""
        self.commit_count += 1

    def rollback(self) -> None:
        """记录回滚动作。"""
        self.rollback_count += 1


def test_query_bid_fill_logs_should_return_matching_logs_and_close_session() -> None:
    """正常场景：应返回日志并关闭独立数据库会话。"""
    expected_logs = [object(), object()]
    session = FakeSession(expected_logs)

    with patch("app.db.session.SessionLocal", return_value=session):
        result = _query_bid_fill_logs("document-1")

    assert result == expected_logs
    assert session.closed is True


def test_query_bid_fill_logs_filter_error_should_fallback_to_recent_logs() -> None:
    """异常场景：条件过滤失败时应降级读取最近日志而不是抛出异常。"""
    matching_log = type("Log", (), {"task_id": "document-2", "inputs": {}})()
    unrelated_log = type("Log", (), {"task_id": "other-document", "inputs": {}})()
    session = FakeSession([matching_log, unrelated_log], fail_filter=True)

    with patch("app.db.session.SessionLocal", return_value=session):
        result = _query_bid_fill_logs("document-2")

    assert result == [matching_log]
    assert session.closed is True


def test_query_bid_fill_logs_without_logs_should_return_empty_list() -> None:
    """边界场景：没有任何审计日志时应返回空列表。"""
    session = FakeSession([])

    with patch("app.db.session.SessionLocal", return_value=session):
        result = _query_bid_fill_logs("document-without-logs")

    assert result == []
    assert session.closed is True


def test_get_first_bid_fill_duration_should_return_persisted_value() -> None:
    """正常场景：应读取文档中已保存的首次全量撰写耗时。"""
    document = type("Document", (), {"parsed_metadata": {"first_bid_fill_duration_ms": 12500}})()
    session = FakeDocumentSession(document)

    result = _get_first_bid_fill_duration_ms(session, "document-1")

    assert result == 12500


def test_get_first_bid_fill_duration_without_valid_metadata_should_return_zero() -> None:
    """边界场景：文档不存在或耗时字段非法时应返回零。"""
    missing_document_session = FakeDocumentSession(None)
    invalid_document = type("Document", (), {"parsed_metadata": {"first_bid_fill_duration_ms": "unknown"}})()
    invalid_document_session = FakeDocumentSession(invalid_document)

    assert _get_first_bid_fill_duration_ms(missing_document_session, "missing-document") == 0
    assert _get_first_bid_fill_duration_ms(invalid_document_session, "document-2") == 0


def test_persist_first_bid_fill_duration_should_save_value_once() -> None:
    """正常场景：首次成功完成后应保存耗时并提交文档元数据。"""
    document = type("Document", (), {"parsed_metadata": {"project_name": "测试项目"}})()
    session = FakeDocumentSession(document)

    _persist_first_bid_fill_duration(session, "document-1", 12500)

    assert document.parsed_metadata == {
        "project_name": "测试项目",
        "first_bid_fill_duration_ms": 12500,
    }
    assert session.commit_count == 1


def test_persist_first_bid_fill_duration_should_not_overwrite_existing_value() -> None:
    """重复完成场景：已有首次耗时基准时不得被后续耗时覆盖。"""
    document = type("Document", (), {"parsed_metadata": {"first_bid_fill_duration_ms": 12500}})()
    session = FakeDocumentSession(document)

    _persist_first_bid_fill_duration(session, "document-1", 99999)

    assert document.parsed_metadata["first_bid_fill_duration_ms"] == 12500
    assert session.commit_count == 0
