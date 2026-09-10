"""解析进度缓存与 SSE 补读逻辑单元测试。"""

import json

import pytest

from app.api import sse
from app.worker import tasks


def test_publish_progress_should_cache_latest_message_before_publish(monkeypatch: pytest.MonkeyPatch) -> None:
    """正常场景：发布进度时应同步缓存最新消息，避免 SSE 建连晚于任务启动。"""
    calls: list[tuple[str, str, str]] = []

    def fake_setex(key: str, ttl: int, payload: str) -> None:
        calls.append(("setex", key, payload))

    def fake_publish(channel: str, payload: str) -> None:
        calls.append(("publish", channel, payload))

    monkeypatch.setattr(tasks.redis_client, "setex", fake_setex)
    monkeypatch.setattr(tasks.redis_client, "publish", fake_publish)

    tasks.publish_progress("task-1", "完成", 100, {"document_id": "doc-1"})

    assert [call[0] for call in calls] == ["setex", "publish"]
    assert calls[0][1] == "progress:task-1"
    assert json.loads(calls[0][2])["result"]["document_id"] == "doc-1"
    assert calls[0][2] == calls[1][2]


class _FakePubSub:
    """用于测试 SSE 生成器的最小 Redis Pub/Sub 替身。"""

    def __init__(self, messages: list[dict[str, str]]) -> None:
        self.messages = messages
        self.subscribed_channel: str | None = None
        self.unsubscribed_channel: str | None = None

    async def subscribe(self, channel: str) -> None:
        self.subscribed_channel = channel

    async def get_message(self, **_: object) -> dict[str, str] | None:
        if self.messages:
            return self.messages.pop(0)
        return None

    async def unsubscribe(self, channel: str) -> None:
        self.unsubscribed_channel = channel


class _FakeRedis:
    """用于测试 SSE 缓存补读和资源释放行为的异步 Redis 替身。"""

    def __init__(self, latest_data: str | None, messages: list[dict[str, str]]) -> None:
        self.latest_data = latest_data
        self.pubsub_instance = _FakePubSub(messages)
        self.closed = False

    def pubsub(self) -> _FakePubSub:
        return self.pubsub_instance

    async def get(self, _: str) -> str | None:
        return self.latest_data

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_redis_event_generator_should_replay_cached_terminal_result(monkeypatch: pytest.MonkeyPatch) -> None:
    """边界场景：任务已完成后才建立 SSE 连接时，应直接补发最终结果并结束。"""
    payload = json.dumps({"status": "完成", "progress": 100, "result": {"document_id": "doc-1"}})
    fake_redis = _FakeRedis(payload, [])

    async def fake_from_url(_: str) -> _FakeRedis:
        return fake_redis

    monkeypatch.setattr(sse.aioredis, "from_url", fake_from_url)

    events = [event async for event in sse.redis_event_generator("task-1")]

    assert len(events) == 1
    assert json.loads(events[0]["data"])["result"]["document_id"] == "doc-1"
    assert fake_redis.pubsub_instance.subscribed_channel == "channel:task-1"
    assert fake_redis.pubsub_instance.unsubscribed_channel == "channel:task-1"
    assert fake_redis.closed is True


@pytest.mark.asyncio
async def test_redis_event_generator_should_follow_live_message_after_cached_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    """正常场景：补读未完成进度后，应继续监听并接收后续完成消息。"""
    cached_payload = json.dumps({"status": "处理中", "progress": 50})
    completed_payload = json.dumps({"status": "完成", "progress": 100})
    fake_redis = _FakeRedis(
        cached_payload,
        [{"data": completed_payload}],
    )

    async def fake_from_url(_: str) -> _FakeRedis:
        return fake_redis

    monkeypatch.setattr(sse.aioredis, "from_url", fake_from_url)

    events = [event async for event in sse.redis_event_generator("task-2")]

    assert [json.loads(event["data"])["progress"] for event in events] == [50, 100]
    assert fake_redis.closed is True
