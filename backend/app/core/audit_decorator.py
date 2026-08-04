import time
import logging
from functools import wraps
from typing import Callable, Any

from app.core.context import current_node_name, current_node_prompt_tokens, current_node_completion_tokens
from app.services.audit_service import audit_service

logger = logging.getLogger(__name__)

def audit_node(name: str) -> Callable:
    """
    LangGraph 节点审计装饰器。
    用于记录进入和退出节点时的状态，计算节点执行耗时，并在节点执行完毕后打印/记录详细的 Token 消耗量。
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(state: dict, *args, **kwargs) -> Any:
            # 注入当前节点名称到全局上下文，并重置当前节点的 Token 计数器
            token_node = current_node_name.set(name)
            token_p = current_node_prompt_tokens.set(0)
            token_c = current_node_completion_tokens.set(0)
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
                exec_time_ms = int((end_time - start_time) * 1000)
                
                # 获取该 Agent 节点内消耗的所有 Token
                p_tok = current_node_prompt_tokens.get()
                c_tok = current_node_completion_tokens.get()
                t_tok = p_tok + c_tok
                
                # 显式打印 Agent 节点执行完成后的 Token 消耗
                logger.info(
                    f"📊 [Agent 节点完成] [{name}] | 耗时: {exec_time_ms}ms | "
                    f"Prompt Tokens: {p_tok:,} | Completion Tokens: {c_tok:,} | "
                    f"Total Tokens: {t_tok:,}"
                )

                safe_state_output = {k: v for k, v in result.items() if k not in ["doc_text", "company_quals"]}
                audit_service.log_event(
                    action_type="node_exec_end",
                    outputs=safe_state_output,
                    prompt_tokens=p_tok,
                    completion_tokens=c_tok,
                    execution_time_ms=exec_time_ms
                )
                return result
            except Exception as e:
                end_time = time.time()
                exec_time_ms = int((end_time - start_time) * 1000)
                p_tok = current_node_prompt_tokens.get()
                c_tok = current_node_completion_tokens.get()
                
                logger.error(
                    f"❌ [Agent 节点异常] [{name}] | 耗时: {exec_time_ms}ms | 错误: {e} | "
                    f"Prompt Tokens: {p_tok:,} | Completion Tokens: {c_tok:,} | Total: {p_tok + c_tok:,}"
                )
                
                audit_service.log_event(
                    action_type="node_exec_end",
                    status="error",
                    error_message=str(e),
                    prompt_tokens=p_tok,
                    completion_tokens=c_tok,
                    execution_time_ms=exec_time_ms
                )
                raise e
            finally:
                current_node_name.reset(token_node)
                current_node_prompt_tokens.reset(token_p)
                current_node_completion_tokens.reset(token_c)
                
        return wrapper
    return decorator

