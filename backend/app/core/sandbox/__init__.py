"""
Agent 沙箱模块 (app.core.sandbox)

暴露 Agent 沙箱的核心组件与统一入口。
"""

from app.core.sandbox.exceptions import (
    SandboxError,
    SandboxPathViolationError,
    SandboxCodeSecurityError,
    SandboxCommandError,
    SandboxNetworkError,
    SandboxBudgetExceededError,
)
from app.core.sandbox.fs_sandbox import FileSystemSandbox
from app.core.sandbox.code_sandbox import CodeExecutionSandbox
from app.core.sandbox.cmd_sandbox import CommandSandbox
from app.core.sandbox.guardrails import AgentGuardrails
from app.core.sandbox.manager import AgentSandbox

__all__ = [
    "SandboxError",
    "SandboxPathViolationError",
    "SandboxCodeSecurityError",
    "SandboxCommandError",
    "SandboxNetworkError",
    "SandboxBudgetExceededError",
    "FileSystemSandbox",
    "CodeExecutionSandbox",
    "CommandSandbox",
    "AgentGuardrails",
    "AgentSandbox",
]
