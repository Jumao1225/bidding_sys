"""
Agent 沙箱异常处理模块 (exceptions.py)

定义 Agent 沙箱在文件系统隔离、代码安全校验、命令行白名单、网络访问控制及行为 Guardrails
中可能抛出的各类专属异常，便于上层捕获与标准化日志/响应。

遵循项目规范：
1. 全面使用中文注释与 Docstrings；
2. 继承自系统基础异常或通用沙箱基类。
"""

class SandboxError(Exception):
    """Agent 沙箱通用异常基类"""
    def __init__(self, message: str, details: dict = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class SandboxPathViolationError(SandboxError):
    """文件系统路径越界/越权操作异常（例如尝试跨越工作区或访问系统敏感目录）"""
    pass


class SandboxCodeSecurityError(SandboxError):
    """代码安全检查未通过异常（例如尝试 import os/subprocess 或使用危急内置函数）"""
    pass


class SandboxCommandError(SandboxError):
    """命令行/子进程执行沙箱异常（例如命令不在白名单中或包含参数注入）"""
    pass


class SandboxNetworkError(SandboxError):
    """网络访问沙箱异常（例如 SSRF 试图访问局域网 IP 或非白名单域名）"""
    pass


class SandboxBudgetExceededError(SandboxError):
    """Agent 行为或资源消耗超出 Guardrails 限制（如 Step 步数超限、Token 消耗溢出、执行超时）"""
    pass
