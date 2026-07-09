import asyncio
import json
from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse
from app.core.config import settings
import redis.asyncio as aioredis
from loguru import logger

router = APIRouter()

async def redis_event_generator(task_id: str):
    """
    订阅 Redis 频道，持续返回任务进度直到完成
    """
    redis = await aioredis.from_url(settings.REDIS_URL)
    pubsub = redis.pubsub()
    channel = f"channel:{task_id}"
    await pubsub.subscribe(channel)
    
    logger.info(f"SSE 建立连接，开始订阅: {channel}")
    try:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message:
                data = message["data"]
                # 已经是 json 字符串
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                
                yield {
                    "event": "message",
                    "id": task_id,
                    "data": data
                }
                
                # 如果进度 100% 或者出错，结束流
                try:
                    parsed = json.loads(data)
                    if parsed.get("progress") == 100 or "错误" in parsed.get("status", ""):
                        break
                except Exception:
                    pass
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
    finally:
        await pubsub.unsubscribe(channel)
        await redis.close()
        
@router.get("/progress/{task_id}")
async def get_task_progress(task_id: str):
    """
    SSE 接口：前端通过此接口监听后台分析任务进度
    """
    return EventSourceResponse(redis_event_generator(task_id))
