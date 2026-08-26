"""标书撰写任务的 Redis 并发控制服务。"""

from dataclasses import dataclass
import multiprocessing
from typing import Callable, Literal, Optional
from uuid import uuid4

import redis
from loguru import logger
from redis.exceptions import RedisError

from app.core.config import settings


ReservationStatus = Literal[
    "accepted",
    "document_running",
    "capacity_reached",
    "redis_unavailable",
]

_RELEASE_LOCK_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


@dataclass(frozen=True)
class BidFillTaskReservation:
    """一次已成功预留的标书撰写任务槽位。"""

    document_lock_key: str
    capacity_lock_key: str
    token: str

    def to_payload(self) -> dict[str, str]:
        """转换为可传递给 Celery 的 JSON 数据。"""
        return {
            "document_lock_key": self.document_lock_key,
            "capacity_lock_key": self.capacity_lock_key,
            "token": self.token,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, str]) -> "BidFillTaskReservation":
        """从 Celery 消息中恢复任务槽位信息。"""
        return cls(
            document_lock_key=payload["document_lock_key"],
            capacity_lock_key=payload["capacity_lock_key"],
            token=payload["token"],
        )


class BidFillTaskService:
    """限制标书撰写任务并防止同一文档被重复写入。"""

    def __init__(self, redis_factory: Optional[Callable[[], redis.Redis]] = None):
        self._redis_factory = redis_factory or self._create_redis_client

    @staticmethod
    def _create_redis_client() -> redis.Redis:
        """创建与任务队列共用的 Redis 客户端。"""
        return redis.from_url(settings.REDIS_URL, decode_responses=True)

    def acquire(self, document_id: str) -> tuple[Optional[BidFillTaskReservation], ReservationStatus]:
        """预留同文档锁和全局并发槽位，避免重任务挤占 Web 进程资源。"""
        token = str(uuid4())
        document_lock_key = f"bid-fill:document:{document_id}"
        lock_ttl_seconds = settings.BID_FILL_LOCK_TTL_SECONDS

        try:
            client = self._redis_factory()
            if not client.set(document_lock_key, token, nx=True, ex=lock_ttl_seconds):
                logger.info(f"标书撰写任务已在运行，拒绝重复提交: document_id={document_id}")
                return None, "document_running"

            for slot_index in range(settings.BID_FILL_MAX_CONCURRENCY):
                capacity_lock_key = f"bid-fill:capacity:{slot_index}"
                if client.set(capacity_lock_key, token, nx=True, ex=lock_ttl_seconds):
                    reservation = BidFillTaskReservation(
                        document_lock_key=document_lock_key,
                        capacity_lock_key=capacity_lock_key,
                        token=token,
                    )
                    logger.info(
                        "已预留标书撰写任务槽位: "
                        f"document_id={document_id}, slot={slot_index}"
                    )
                    return reservation, "accepted"

            self._release_key(client, document_lock_key, token)
            logger.warning("标书撰写并发槽位已满，拒绝新增任务")
            return None, "capacity_reached"
        except RedisError as exc:
            logger.exception(f"预留标书撰写任务槽位失败: document_id={document_id}, error={exc}")
            return None, "redis_unavailable"

    def release(self, reservation: BidFillTaskReservation) -> None:
        """仅由持有者释放任务锁，避免误删后续任务的锁。"""
        try:
            client = self._redis_factory()
            self._release_key(client, reservation.document_lock_key, reservation.token)
            self._release_key(client, reservation.capacity_lock_key, reservation.token)
            logger.info("已释放标书撰写任务槽位")
        except RedisError as exc:
            logger.exception(f"释放标书撰写任务槽位失败: error={exc}")

    @staticmethod
    def _release_key(client: redis.Redis, key: str, token: str) -> None:
        """使用 Lua 比较并删除锁，确保锁超时重分配后不会误删。"""
        client.eval(_RELEASE_LOCK_SCRIPT, 1, key, token)


bid_fill_task_service = BidFillTaskService()


def run_bid_fill_task_in_process(
    document_id: str,
    user_id: str,
    tenant_id: str,
    custom_instructions: Optional[str],
    category_hints: Optional[dict],
    reservation_data: dict[str, str],
) -> None:
    """在独立 Python 进程中执行撰写，并在结束后释放 Redis 槽位。"""
    from app.api.endpoints.bid_generator import _run_agent_bid_filling_in_background

    reservation = BidFillTaskReservation.from_payload(reservation_data)
    try:
        _run_agent_bid_filling_in_background(
            document_id=document_id,
            u_id=user_id,
            t_id=tenant_id,
            custom_instructions=custom_instructions,
            category_hints=category_hints,
        )
    finally:
        bid_fill_task_service.release(reservation)


def start_bid_fill_process(
    document_id: str,
    user_id: str,
    tenant_id: str,
    custom_instructions: Optional[str],
    category_hints: Optional[dict],
    reservation_data: dict[str, str],
) -> int:
    """启动与 Web 服务隔离的标书撰写子进程并返回其进程 ID。"""
    process_context = multiprocessing.get_context("spawn")
    process = process_context.Process(
        target=run_bid_fill_task_in_process,
        kwargs={
            "document_id": document_id,
            "user_id": user_id,
            "tenant_id": tenant_id,
            "custom_instructions": custom_instructions,
            "category_hints": category_hints,
            "reservation_data": reservation_data,
        },
        daemon=False,
    )
    process.start()
    logger.info(f"已启动独立标书撰写进程: document_id={document_id}, pid={process.pid}")
    return process.pid
