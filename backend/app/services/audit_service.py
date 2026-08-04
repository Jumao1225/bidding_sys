import time
import uuid
import logging
from functools import wraps
from typing import Callable, Any, Optional

from app.core.context import (
    current_task_id,
    current_node_name,
    current_node_prompt_tokens,
    current_node_completion_tokens,
)

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
        error_message: Optional[str] = None,
        task_id: Optional[str] = None,
        node_name: Optional[str] = None,
    ):
        """
        统一的审计日志写入入口。
        优先从 ContextVar 获取 task_id 和 node_name，缺失时采用兜底标识，确保日志绝不丢失。
        并实时累加当前 Node 执行期间消耗的 Prompt Tokens 与 Completion Tokens。
        """
        resolved_task_id = task_id or current_task_id.get() or f"sync-{uuid.uuid4().hex[:8]}"
        resolved_node_name = node_name or current_node_name.get() or "service_direct_call"

        # 实时累加当前 Agent 节点执行期间的 Token 消耗
        if prompt_tokens or completion_tokens:
            p_val = current_node_prompt_tokens.get()
            c_val = current_node_completion_tokens.get()
            current_node_prompt_tokens.set(p_val + (prompt_tokens or 0))
            current_node_completion_tokens.set(c_val + (completion_tokens or 0))

            
        try:
            from app.worker.tasks import async_write_audit_log
            # 直接同步调用该函数持久化写库，避免 Redis 队列依赖丢失
            async_write_audit_log(
                task_id=resolved_task_id,
                node_name=resolved_node_name,
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
            # 记录发送失败，绝不中断主业务流程
            logger.error(f"Failed to dispatch audit log task: {e}")

audit_service = AuditService()

