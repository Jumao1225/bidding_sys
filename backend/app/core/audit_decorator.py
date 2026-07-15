import time
import logging
from functools import wraps
from typing import Callable, Any

from app.core.context import current_node_name
from app.services.audit_service import audit_service

logger = logging.getLogger(__name__)

def audit_node(name: str) -> Callable:
    """
    LangGraph 节点审计装饰器。
    用于记录进入和退出节点时的状态，计算节点执行耗时。
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(state: dict, *args, **kwargs) -> Any:
            # 注入当前节点名称到全局上下文
            token = current_node_name.set(name)
            start_time = time.time()
            
            # 记录节点开始 (仅记录基础结构，不记录全量 doc_text 防止包过大)
            safe_state_input = {k: v for k, v in state.items() if k not in ["doc_text", "company_quals"]}
            audit_service.log_event(
                action_type="node_exec_start",
                inputs=safe_state_input
            )
            
            try:
                result = func(state, *args, **kwargs)
                end_time = time.time()
                
                safe_state_output = {k: v for k, v in result.items() if k not in ["doc_text", "company_quals"]}
                audit_service.log_event(
                    action_type="node_exec_end",
                    outputs=safe_state_output,
                    execution_time_ms=int((end_time - start_time) * 1000)
                )
                return result
            except Exception as e:
                end_time = time.time()
                audit_service.log_event(
                    action_type="node_exec_end",
                    status="error",
                    error_message=str(e),
                    execution_time_ms=int((end_time - start_time) * 1000)
                )
                raise e
            finally:
                current_node_name.reset(token)
                
        return wrapper
    return decorator
