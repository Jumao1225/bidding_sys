from unittest.mock import MagicMock, patch

from app.core.config import settings
from app.services.bid_fill_task_service import BidFillTaskService, start_bid_fill_process


class FakeRedis:
    """用于验证 Redis 锁语义的内存替身。"""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def set(self, key: str, value: str, nx: bool = False, ex: int | None = None) -> bool:
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def eval(self, _script: str, _num_keys: int, key: str, token: str) -> int:
        if self.values.get(key) != token:
            return 0
        del self.values[key]
        return 1


def test_acquire_same_document_should_reject_duplicate_task() -> None:
    """同一份标书已在执行时，后续提交必须被拒绝。"""
    fake_redis = FakeRedis()
    service = BidFillTaskService(redis_factory=lambda: fake_redis)

    first_reservation, first_status = service.acquire("document-1")
    second_reservation, second_status = service.acquire("document-1")

    assert first_reservation is not None
    assert first_status == "accepted"
    assert second_reservation is None
    assert second_status == "document_running"


def test_acquire_capacity_reached_should_reject_another_document(monkeypatch) -> None:
    """全局撰写槽位已满时，另一份标书不得继续进入队列。"""
    fake_redis = FakeRedis()
    service = BidFillTaskService(redis_factory=lambda: fake_redis)
    monkeypatch.setattr(
        "app.services.bid_fill_task_service.settings.BID_FILL_MAX_CONCURRENCY",
        1,
    )

    first_reservation, _ = service.acquire("document-1")
    second_reservation, second_status = service.acquire("document-2")

    assert first_reservation is not None
    assert second_reservation is None
    assert second_status == "capacity_reached"
    assert "bid-fill:document:document-2" not in fake_redis.values


def test_default_bid_fill_concurrency_should_allow_different_documents() -> None:
    """默认配置应允许不同标书同时进入两个独立并发槽位。"""
    fake_redis = FakeRedis()
    service = BidFillTaskService(redis_factory=lambda: fake_redis)

    first_reservation, first_status = service.acquire("document-1")
    second_reservation, second_status = service.acquire("document-2")

    assert settings.BID_FILL_MAX_CONCURRENCY >= 2
    assert first_reservation is not None
    assert first_status == "accepted"
    assert second_reservation is not None
    assert second_status == "accepted"


def test_acquire_different_documents_with_two_slots_should_accept_both(monkeypatch) -> None:
    """不同标书在有两个槽位时应分别获得任务锁。"""
    fake_redis = FakeRedis()
    service = BidFillTaskService(redis_factory=lambda: fake_redis)
    monkeypatch.setattr(
        "app.services.bid_fill_task_service.settings.BID_FILL_MAX_CONCURRENCY",
        2,
    )

    first_reservation, first_status = service.acquire("document-1")
    second_reservation, second_status = service.acquire("document-2")

    assert first_reservation is not None
    assert first_status == "accepted"
    assert second_reservation is not None
    assert second_status == "accepted"
    assert fake_redis.values["bid-fill:capacity:0"] == first_reservation.token
    assert fake_redis.values["bid-fill:capacity:1"] == second_reservation.token


def test_release_valid_reservation_should_free_document_and_capacity_locks() -> None:
    """任务结束时应同时释放文档锁和全局并发槽位。"""
    fake_redis = FakeRedis()
    service = BidFillTaskService(redis_factory=lambda: fake_redis)
    reservation, status = service.acquire("document-1")

    assert status == "accepted"
    assert reservation is not None
    service.release(reservation)

    assert fake_redis.values == {}


def test_start_bid_fill_process_should_start_spawned_process_and_return_pid() -> None:
    """提交标书撰写时应启动独立进程，并将进程 ID 返回给接口层。"""
    mock_context = MagicMock()
    mock_process = MagicMock(pid=24680)
    mock_context.Process.return_value = mock_process

    with patch(
        "app.services.bid_fill_task_service.multiprocessing.get_context",
        return_value=mock_context,
    ):
        process_id = start_bid_fill_process(
            document_id="document-1",
            user_id="user-1",
            tenant_id="tenant-1",
            custom_instructions=None,
            category_hints=None,
            reservation_data={
                "document_lock_key": "bid-fill:document:document-1",
                "capacity_lock_key": "bid-fill:capacity:0",
                "token": "lock-token",
            },
        )

    assert process_id == 24680
    mock_context.Process.assert_called_once()
    mock_process.start.assert_called_once()
