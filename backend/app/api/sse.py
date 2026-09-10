import asyncio
import json
from collections.abc import AsyncGenerator
from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse
from app.core.config import settings
import redis.asyncio as aioredis
from loguru import logger

router = APIRouter()


def _decode_progress_data(data: bytes | str) -> str:
    """将 Redis 返回的字节或字符串统一转换为 JSON 文本。"""
    if isinstance(data, bytes):
        return data.decode("utf-8")
    return data


def _is_terminal_progress(data: str) -> bool:
    """判断进度消息是否代表任务已经结束。"""
    try:
        parsed = json.loads(data)
    except (TypeError, ValueError) as exc:
        logger.debug("SSE 进度消息不是有效 JSON，继续保持连接: {}", exc)
        return False

    if not isinstance(parsed, dict):
        logger.debug("SSE 进度消息不是对象，继续保持连接")
        return False

    return parsed.get("progress") == 100 or "错误" in parsed.get("status", "")


def _build_progress_event(task_id: str, data: bytes | str) -> dict[str, str]:
    """构造统一格式的 SSE 进度事件。"""
    decoded_data = _decode_progress_data(data)
    return {
        "event": "message",
        "id": task_id,
        "data": decoded_data,
    }

async def redis_event_generator(task_id: str) -> AsyncGenerator[dict[str, str], None]:
    """
    订阅 Redis 频道，持续返回任务进度直到完成
    """
    redis = await aioredis.from_url(settings.REDIS_URL)
    pubsub = redis.pubsub()
    channel = f"channel:{task_id}"
    try:
        await pubsub.subscribe(channel)
        logger.info(f"SSE 建立连接，开始订阅: {channel}")

        # 任务线程可能早于浏览器建立 SSE 连接，先读取缓存避免错过最终结果。
        latest_data = await redis.get(f"progress:{task_id}")
        if latest_data is not None:
            decoded_latest_data = _decode_progress_data(latest_data)
            yield _build_progress_event(task_id, decoded_latest_data)
            if _is_terminal_progress(decoded_latest_data):
                return

        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message:
                data = _decode_progress_data(message["data"])
                yield _build_progress_event(task_id, data)

                # 如果进度 100% 或者出错，结束流。
                if _is_terminal_progress(data):
                    break
            else:
                # keep-alive
                yield {
                    "event": "ping",
                    "id": task_id,
                    "data": "keep-alive"
                }
            await asyncio.sleep(0.5)
    except asyncio.CancelledError:
        logger.info(f"客户端断开 SSE 连接: {channel}")
    except Exception:
        logger.exception(f"SSE 进度流异常: {channel}")
        raise
    finally:
        try:
            await pubsub.unsubscribe(channel)
        except Exception:
            logger.exception(f"SSE 取消订阅失败: {channel}")
        await redis.close()
        
@router.get("/progress/{task_id}")
async def get_task_progress(task_id: str):
    """
    SSE 接口：前端通过此接口监听后台分析任务进度
    """
    return EventSourceResponse(redis_event_generator(task_id))
