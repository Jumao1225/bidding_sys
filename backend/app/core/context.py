import contextvars

# 用于全链路追踪当前 Celery Task ID
current_task_id = contextvars.ContextVar("current_task_id", default=None)

# 用于全链路追踪当前执行的 LangGraph Node 名称
current_node_name = contextvars.ContextVar("current_node_name", default="unknown")

# 用于租户隔离与安全校验：记录当前请求的 user_id 和 tenant_id
current_user_id = contextvars.ContextVar("current_user_id", default=None)
current_tenant_id = contextvars.ContextVar("current_tenant_id", default=None)
