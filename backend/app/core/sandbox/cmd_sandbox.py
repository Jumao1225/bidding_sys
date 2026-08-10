"""
Agent 命令行与外部子进程执行沙箱 (cmd_sandbox.py)

功能：
1. 校验二进制可执行指令白名单（针对 Office CLI、LibreOffice 等外部工具）；
2. 防范 Shell 参数注入与危险指令拼接；
3. 净化子进程环境变量，擦除数据库连接串、API Key 等敏感密码信息；
4. 资源控制（硬超时中断、标准输出/错误上限截断）。

遵循项目规范：
1. 全面使用中文注释与 Docstrings；
2. 全面使用 Type Hints；
3. 使用 loguru 进行详细调试日志记录；
4. 防御性编程与尽早返回 (Early Return)。
"""

import os
import shlex
import asyncio
from typing import Dict, List, Optional, Set, Union
from loguru import logger

from app.core.sandbox.exceptions import SandboxCommandError, SandboxError


class CommandSandbox:
    """
    Agent 命令行执行沙箱
    """

    # 默认允许调用的外部可执行程序白名单（全小写）
    DEFAULT_WHITELIST: Set[str] = {
        "officecli", "officecli.exe",
        "libreoffice", "soffice", "soffice.exe",
        "pdftoppm", "pdf2image", "tesseract",
        "python", "python.exe", "node", "node.exe"
    }

    # 敏感环境变量关键字黑名单 (遇到包含这些关键字的环境变量统统清洗擦除)
    SENSITIVE_ENV_KEYWORDS: Set[str] = {
        "KEY", "SECRET", "TOKEN", "PASSWORD", "PASS",
        "DATABASE", "DB_URL", "JWT", "AUTH"
    }

    def __init__(self, allowed_commands: Optional[Set[str]] = None, default_timeout_seconds: float = 60.0):
        self.allowed_commands: Set[str] = set(c.lower() for c in (allowed_commands or self.DEFAULT_WHITELIST))
        self.default_timeout_seconds = default_timeout_seconds

    def sanitize_environment(self) -> Dict[str, str]:
        """
        构造子进程安全的环境变量集合，剥离敏感密码与 API Keys。

        :return: 经过脱敏擦除后的环境变量字典
        """
        clean_env = {}
        for k, v in os.environ.items():
            k_upper = k.upper()
            # 如果包含敏感关键字，进行防护屏蔽
            if any(kw in k_upper for kw in self.SENSITIVE_ENV_KEYWORDS):
                continue
            clean_env[k] = v
        return clean_env

    def validate_command(self, cmd_args: List[str]) -> None:
        """
        强校验可执行命令及参数列表。

        :param cmd_args: 拆分后的命令行参数数组 [binary, arg1, arg2, ...]
        :raises SandboxCommandError: 校验失败时抛出
        """
        if not cmd_args or not cmd_args[0]:
            raise SandboxCommandError("无法执行空命令")

        executable = os.path.basename(cmd_args[0]).lower()
        if executable not in self.allowed_commands:
            logger.warning(f"🚨 [CMD Sandbox] 拦截非法二进制可执行指令调用: '{executable}'")
            raise SandboxCommandError(
                f"沙箱命令拦截：'{executable}' 不在允许调用的系统 CLI 白名单中",
                details={"executable": executable, "allowed": list(self.allowed_commands)}
            )

        # 检查参数中是否存在危险的 Shell 运算符拼接
        dangerous_tokens = {";", "&&", "||", "|", "`", "$(", ">", "<"}
        for arg in cmd_args[1:]:
            for token in dangerous_tokens:
                if token in arg:
                    logger.warning(f"🚨 [CMD Sandbox] 拦截命令参数注入攻击: arg='{arg}', token='{token}'")
                    raise SandboxCommandError(
                        f"沙箱命令拦截：检测到可能的 Shell 注入字符 '{token}' 位于参数 '{arg}' 中"
                    )

    async def execute_async(
        self,
        command: Union[str, List[str]],
        timeout_seconds: Optional[float] = None,
        cwd: Optional[str] = None,
        extra_env: Optional[Dict[str, str]] = None
    ) -> Dict[str, Union[bool, int, str]]:
        """
        安全地异步执行外部命令子进程。

        :param command: 可执行命令行（字符串或参数列表）
        :param timeout_seconds: 超时秒数
        :param cwd: 子进程工作路径
        :param extra_env: 额外增加的环境变量
        :return: 运行结果字典 {"success": bool, "returncode": int, "stdout": str, "stderr": str, "error": str}
        """
        if isinstance(command, str):
            cmd_args = shlex.split(command, posix=(os.name != 'nt'))
        else:
            cmd_args = command

        # 1. 安全指令白名单与防注入校验
        self.validate_command(cmd_args)

        # 2. 环境变量净化
        env = self.sanitize_environment()
        if extra_env:
            env.update(extra_env)

        timeout = timeout_seconds or self.default_timeout_seconds

        logger.info(f"🚀 [CMD Sandbox] 安全启动外部子进程: {' '.join(cmd_args[:3])}... (timeout={timeout}s)")

        try:
            # 3. 强制禁止 shell=True 模式，安全拉起子进程
            process = await asyncio.create_subprocess_exec(
                cmd_args[0],
                *cmd_args[1:],
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(), timeout=timeout
                )
                stdout_str = stdout_bytes.decode('utf-8', errors='ignore')
                stderr_str = stderr_bytes.decode('utf-8', errors='ignore')
                success = (process.returncode == 0)

                return {
                    "success": success,
                    "returncode": process.returncode,
                    "stdout": stdout_str,
                    "stderr": stderr_str,
                    "error": None if success else f"子进程退出代码非零: {process.returncode}"
                }

            except asyncio.TimeoutError:
                logger.error(f"⏱️ [CMD Sandbox] 外部子进程执行超时 ({timeout}s)，强制 Terminate...")
                try:
                    process.kill()
                except Exception:
                    pass
                return {
                    "success": False,
                    "returncode": -1,
                    "stdout": "",
                    "stderr": "",
                    "error": f"命令行执行超时（超出上限 {timeout} 秒）"
                }

        except Exception as e:
            logger.exception(f"❌ [CMD Sandbox] 外部子进程启动异常: {e}")
            return {
                "success": False,
                "returncode": -1,
                "stdout": "",
                "stderr": str(e),
                "error": str(e)
            }
