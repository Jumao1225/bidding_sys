import contextvars

# 用于全链路追踪当前 Celery Task ID
current_task_id = contextvars.ContextVar("current_task_id", default=None)

# 用于全链路追踪当前执行的 LangGraph Node 名称
current_node_name = contextvars.ContextVar("current_node_name", default="unknown")
