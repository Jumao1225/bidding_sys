import time
import logging
from functools import wraps
from typing import Callable, Any, Optional

from app.core.context import current_task_id, current_node_name

logger = logging.getLogger(__name__)

class AuditService:
    @staticmethod
    def log_event(
        action_type: str,
        inputs: Optional[dict] = None,
        outputs: Optional[dict] = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        execution_time_ms: Optional[int] = None,
        status: str = "success",
        error_message: Optional[str] = None
    ):
        """
        统一的审计日志写入入口。
        自动从 ContextVar 获取 task_id 和 node_name，并推送到 Celery 异步队列。
        """
        task_id = current_task_id.get()
        node_name = current_node_name.get()
        
        if not task_id:
            logger.debug(f"Audit log skipped (no task_id context): {action_type}")
            return
            
        try:
            from app.worker.tasks import async_write_audit_log
            # 因为当前已经处于 FastAPI 的 BackgroundTasks 线程中，
            # 这里直接同步调用该函数，不再使用 Celery 的 .delay() 推送 Redis。
            async_write_audit_log(
                task_id=task_id,
                node_name=node_name,
                action_type=action_type,
                inputs=inputs,
                outputs=outputs,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                execution_time_ms=execution_time_ms,
                status=status,
                error_message=error_message
            )
        except Exception as e:
            # 记录发送失败，绝不中断主流程
            logger.error(f"Failed to dispatch audit log task: {e}")

audit_service = AuditService()
