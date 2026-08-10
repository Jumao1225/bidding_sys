"""
Agent 沙箱统一管理类与门面 (manager.py)

功能：
组装文件沙箱 (FileSystemSandbox)、代码沙箱 (CodeExecutionSandbox)、命令行沙箱 (CommandSandbox)
及防护规则 (AgentGuardrails)，对外提供极简统一的门面 (Facade) 接口与上下文管理器支持。

遵循项目规范：
1. 全面使用中文注释与 Docstrings；
2. 全面使用 Type Hints；
3. 使用 loguru 进行详细调试日志记录；
4. 防御性编程与尽早返回 (Early Return)。
"""

from typing import Dict, List, Optional, Any, Union
from loguru import logger

from app.core.sandbox.exceptions import SandboxError
from app.core.sandbox.fs_sandbox import FileSystemSandbox
from app.core.sandbox.code_sandbox import CodeExecutionSandbox
from app.core.sandbox.cmd_sandbox import CommandSandbox
from app.core.sandbox.guardrails import AgentGuardrails


class AgentSandbox:
    """
    Agent 综合运行沙箱 Unified Manager
    """

    def __init__(
        self,
        session_id: Optional[str] = None,
        allowed_paths: Optional[List[str]] = None,
        auto_clean: bool = True,
        max_steps: int = 15,
        max_tokens: int = 200000,
        max_duration_seconds: float = 180.0
    ):
        """
        初始化 Agent 统一沙箱。

        :param session_id: 当前 Agent 会话/任务 ID
        :param allowed_paths: 允许读写的显式授权外部文件/目录列表
        :param auto_clean: 退出沙箱上下文时是否自动清理工作区
        :param max_steps: 最大 Step 步数
        :param max_tokens: 最大 Token 消耗限额
        :param max_duration_seconds: 最大硬超时秒数
        """
        self.auto_clean = auto_clean
        
        # 1. 实例化文件系统沙箱
        self.fs = FileSystemSandbox(
            session_id=session_id,
            allowed_paths=allowed_paths
        )

        # 2. 实例化代码安全沙箱
        self.code = CodeExecutionSandbox()

        # 3. 实例化命令行沙箱
        self.cmd = CommandSandbox()

        # 4. 实例化 Guardrails 规则
        self.guardrails = AgentGuardrails(
            max_steps=max_steps,
            max_tokens=max_tokens,
            max_duration_seconds=max_duration_seconds
        )

        logger.info(f"🧱 [Agent Sandbox] 综合沙箱已成功创建，Session ID: {self.fs.session_id}")

    @property
    def session_id(self) -> str:
        return self.fs.session_id

    @property
    def workspace_dir(self) -> str:
        return self.fs.ensure_workspace()

    def add_allowed_path(self, path: str) -> None:
        """扩展白名单授权路径"""
        self.fs.add_allowed_path(path)

    def resolve_path(self, path: str, must_exist: bool = False) -> str:
        """路径边界越界校验"""
        return self.fs.resolve_path(path, must_exist=must_exist)

    def transaction(self, target_files: Optional[List[str]] = None):
        """标书文件修改的原子事务与快照回滚上下文管理器"""
        return self.fs.transaction(target_files)

    def execute_code(self, code_str: str, extra_globals: Optional[Dict[str, Any]] = None, timeout_seconds: Optional[float] = None) -> Dict[str, Any]:
        """安全地在代码沙箱中运行 Python 代码"""
        self.guardrails.check_timeout()
        return self.code.execute(code_str, extra_globals=extra_globals, timeout_seconds=timeout_seconds)

    async def run_command(self, command: Union[str, List[str]], timeout_seconds: Optional[float] = None, cwd: Optional[str] = None) -> Dict[str, Any]:
        """安全地在 CLI 沙箱中运行外部命令"""
        self.guardrails.check_timeout()
        # 若未指定 cwd，默认限定在沙箱工作区
        work_dir = cwd or self.workspace_dir
        return await self.cmd.execute_async(command, timeout_seconds=timeout_seconds, cwd=work_dir)

    def record_step(self, tool_name: str = "", tool_args_str: str = "") -> None:
        """记录步数并进行死循环/步数上限监控"""
        self.guardrails.record_step(tool_name, tool_args_str)

    def record_tokens(self, prompt_tokens: int, completion_tokens: int) -> None:
        """记录 Token 消费"""
        self.guardrails.record_tokens(prompt_tokens, completion_tokens)

    def __enter__(self):
        """上下文管理器入口：自动确保隔离工作区准备完毕"""
        self.fs.ensure_workspace()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口：如果设置了 auto_clean，自动清理临时工作区"""
        if self.auto_clean:
            self.fs.clean_workspace()
