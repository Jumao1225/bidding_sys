"""
Agent 行为防护与预算 Guardrails 模块 (guardrails.py)

功能：
1. Agent 步数限制（Step Limit）：防护 ReAct 循环或 Supervisor-Worker 死循环调工具；
2. 死循环模式检测（Infinite Loop Detection）：识别连续重复调用相同工具及入参行为并提前熔断；
3. Token 消耗预算限额管理（Token Budget Guardrail）；
4. 全局超时看门狗（Global Execution Timeout）。

遵循项目规范：
1. 全面使用中文注释与 Docstrings；
2. 全面使用 Type Hints；
3. 使用 loguru 进行详细调试日志记录；
4. 防御性编程与尽早返回 (Early Return)。
"""

import time
from typing import Dict, List, Optional, Tuple
from loguru import logger

from app.core.sandbox.exceptions import SandboxBudgetExceededError, SandboxError


class AgentGuardrails:
    """
    Agent 行为与资源消耗配额防护 Guardrails
    """

    def __init__(
        self,
        max_steps: int = 15,
        max_tokens: int = 200000,
        max_duration_seconds: float = 180.0,
        max_repeated_tool_calls: int = 3
    ):
        """
        初始化 Agent Guardrails 规则。

        :param max_steps: 单次任务允许最大 ReAct/Tool 步数
        :param max_tokens: 允许最大累计消耗 Token 预算
        :param max_duration_seconds: 全局允许最大硬超时秒数
        :param max_repeated_tool_calls: 判定死循环的连续完全相同工具调用频次
        """
        self.max_steps = max_steps
        self.max_tokens = max_tokens
        self.max_duration_seconds = max_duration_seconds
        self.max_repeated_tool_calls = max_repeated_tool_calls

        # 实时运行状态追踪
        self.current_step: int = 0
        self.total_prompt_tokens: int = 0
        self.total_completion_tokens: int = 0
        self.start_time: float = time.time()
        self.tool_call_history: List[Tuple[str, str]] = []

        logger.debug(f"🛡️ [Agent Guardrails] 初始化防护屏障: max_steps={max_steps}, max_tokens={max_tokens}, timeout={max_duration_seconds}s")

    def reset(self) -> None:
        """
        重置 Guardrails 计数器。
        """
        self.current_step = 0
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.start_time = time.time()
        self.tool_call_history.clear()

    def check_timeout(self) -> None:
        """
        检查全局硬超时。
        :raises SandboxBudgetExceededError: 超时抛出
        """
        elapsed = time.time() - self.start_time
        if elapsed > self.max_duration_seconds:
            logger.error(f"🚨 [Agent Guardrails] 全局执行超时: 已运行 {elapsed:.2f}s, 超过上限 {self.max_duration_seconds}s")
            raise SandboxBudgetExceededError(
                f"Agent 任务全局超时熔断：已运行 {elapsed:.1f} 秒，超过上限 {self.max_duration_seconds} 秒",
                details={"elapsed_seconds": elapsed, "max_duration_seconds": self.max_duration_seconds}
            )

    def record_step(self, tool_name: str = "", tool_args_str: str = "") -> None:
        """
        记录并校验 Agent 执行步数及死循环。

        :param tool_name: 当前调用的工具名称
        :param tool_args_str: 当前工具调用的参数文本
        :raises SandboxBudgetExceededError: 当步数超限或检测到死循环时抛出
        """
        self.check_timeout()
        self.current_step += 1

        # 校验 1：步数限制
        if self.current_step > self.max_steps:
            logger.error(f"🚨 [Agent Guardrails] Step 步数越界熔断: current={self.current_step}, max={self.max_steps}")
            raise SandboxBudgetExceededError(
                f"Agent 执行步数超限熔断：当前第 {self.current_step} 步，最大允许 {self.max_steps} 步",
                details={"current_step": self.current_step, "max_steps": self.max_steps}
            )

        # 校验 2：重复工具调用死循环检测
        if tool_name:
            current_call = (tool_name, tool_args_str or "")
            self.tool_call_history.append(current_call)

            # 检视最近 N 次调用是否完全一致
            if len(self.tool_call_history) >= self.max_repeated_tool_calls:
                recent_calls = self.tool_call_history[-self.max_repeated_tool_calls:]
                if all(call == current_call for call in recent_calls):
                    logger.error(f"🚨 [Agent Guardrails] 检测到 Agent 死循环调工具: tool='{tool_name}' 已连续重复调用 {self.max_repeated_tool_calls} 次")
                    raise SandboxBudgetExceededError(
                        f"Agent 死循环死锁熔断：连续 {self.max_repeated_tool_calls} 次重复调用相同工具 '{tool_name}' 且入参完全相同",
                        details={"tool_name": tool_name, "repeat_count": self.max_repeated_tool_calls}
                    )

        logger.debug(f"🛡️ [Agent Guardrails] 步数校验通过: {self.current_step}/{self.max_steps} (tool='{tool_name}')")

    def record_tokens(self, prompt_tokens: int, completion_tokens: int) -> None:
        """
        记录并校验 Token 消费。

        :param prompt_tokens: 输入 Token
        :param completion_tokens: 输出 Token
        :raises SandboxBudgetExceededError: 当 Token 超限时抛出
        """
        self.total_prompt_tokens += max(0, prompt_tokens)
        self.total_completion_tokens += max(0, completion_tokens)
        total_tokens = self.total_prompt_tokens + self.total_completion_tokens

        if total_tokens > self.max_tokens:
            logger.error(f"🚨 [Agent Guardrails] Token 预算溢出熔断: consumed={total_tokens}, max={self.max_tokens}")
            raise SandboxBudgetExceededError(
                f"Agent Token 预算溢出熔断：已消耗 {total_tokens} tokens，配额上限 {self.max_tokens}",
                details={"total_tokens": total_tokens, "max_tokens": self.max_tokens}
            )
