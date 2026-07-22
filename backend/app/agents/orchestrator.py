import json
from typing import Literal, List, Dict
from pydantic import BaseModel, Field
from app.agents.state import BiddingState
from app.services.llm_service import llm_service
from loguru import logger


class SupervisorDecision(BaseModel):
    next: List[Literal[
        "master_agent", "strategy_qual", "strategy_risk",
        "cost_estimation", "writer_agent", "FINISH", "WAIT"
    ]] = Field(description="The next worker(s) to execute. Output multiple for parallel execution. Output ['WAIT'] to yield control.")
    reasoning: str = Field(description="The reasoning behind this decision. This will be shown to the user, so keep it concise and professional.")

MAX_RETRIES = 2

def build_supervisor_prompt(completed: List[str], running: List[str], retry_counts: Dict[str, int], summaries: List[Dict], state: BiddingState) -> str:
    return f"""
你是一位高级项目总控 Agent (Supervisor)，负责指挥以下 5 个专项 Worker 完成复杂的招标文件分析任务。

【Worker 清单与职责】：
1. master_agent：提取项目的5大基础元数据（如时间、财务、工程等）。【前置条件】：必须最先执行。
2. strategy_qual：资质评估专家，评估本公司资质是否满足标书要求。【前置条件】：依赖 master_agent。
3. strategy_risk：法务风控专家，扫描标书中的各种风险条款和暗坑。【前置条件】：依赖 master_agent。
4. cost_estimation：成本核算专家，计算物料成本底价。【前置条件】：依赖 master_agent。
5. writer_agent：标书文案专家，负责生成最终的偏离表和标书初稿。【前置条件】：依赖前三者（strategy_qual, strategy_risk, cost_estimation）全部完成。

【当前执行状态】：
- ✅ 已成功完成的 Worker：{json.dumps(completed, ensure_ascii=False)}
- 🔄 正在运行中的 Worker：{json.dumps(running, ensure_ascii=False)}
- 📊 各 Worker 失败重试次数：{json.dumps(retry_counts, ensure_ascii=False)} （上限 {MAX_RETRIES} 次）

【决策规则 (Autonomous Orchestration)】：
1. 请根据前置条件，决定下一步的动作。绝不能重复调度已经在【已成功完成】或【正在运行中】的 Worker。
2. 【自主并发】：如果你发现有多个未开始的任务，它们的前置条件都已满足，请你自主决定将它们作为一个数组同时返回（例如：`["strategy_qual", "strategy_risk", "cost_estimation"]`），开启并发执行。
3. 【自主等待】：如果某些任务（如 writer_agent）的前置条件还未满足，且你需要等待【正在运行中】的 Worker 跑完，请你自主决定返回 `["WAIT"]`，什么都不做，等待下一回合。
4. 只有当 5 个 Worker 全部【已成功完成】（或因重试超限被跳过）时，才能返回 `["FINISH"]`。

请提供你的决策理由和下一步要调度的 Worker 数组。
"""

def supervisor_node(state: BiddingState) -> dict:
    """
    Supervisor 动态调度节点。
    每次 Worker 完成后被调用，决定下一步或宣告完成。
    """
    from app.worker.tasks import emit_agent_log
    task_id = state.get("task_id")
    completed = state.get("completed_steps", [])
    running = state.get("running_steps", [])
    retry_counts = state.get("retry_counts", {})
    summaries = state.get("worker_summaries", [])

    prompt = build_supervisor_prompt(completed, running, retry_counts, summaries, state)
    
    # 强制大模型输出结构化决策 (使用较高的 temperature 防止局部复读机现象)
    decision_obj = llm_service.generate_structured_output(
        prompt=prompt,
        schema_cls=SupervisorDecision,
        temperature=0.5
    )

    next_workers = decision_obj.next
    reasoning = decision_obj.reasoning

    # 过滤掉 WAIT
    next_workers = [w for w in next_workers if w != "WAIT"]

    # 更新 running_steps 状态，防止重复派发
    current_running = list(set(running + next_workers))
    state["running_steps"] = current_running

    # 向前端推送 Supervisor 的动态决策
    logger.info(f"[Supervisor] Decision: Next workers -> {next_workers}, Reason: {reasoning}")
    
    # 只有当非 FINISH 且有新任务时，或者完全等待时推送状态
    worker_label = ", ".join(next_workers) if next_workers else "WAIT"
    emit_agent_log(
        log_type="info",
        content=f"🧠 Supervisor 决策 → [{worker_label}] 原因: {reasoning}",
        extra={
            "type": "supervisor_decision",
            "worker": next_workers,  # 现在是个 List[str]
            "reasoning": reasoning,
            "completed_steps": completed,
            "retry_counts": retry_counts
        }
    )

    return {"next": next_workers, "running_steps": current_running}
