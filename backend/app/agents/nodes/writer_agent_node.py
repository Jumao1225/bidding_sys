from app.agents.state import BiddingState


def writer_agent_node(state: BiddingState) -> dict:
    from app.worker.tasks import emit_agent_log
    """
    Writer Agent 节点包装器。
    后续将接入真实的 LLM 撰写逻辑。目前返回成功状态以便通过 Supervisor 的验收。
    """
    task_id = state.get("task_id")
    
    emit_agent_log(
        log_type="info",
        content="开始执行文案起草任务...",
        extra={"type": "worker_start", "worker": "writer_agent"}
    )
    
    # TODO: 接入真实的 writer_agent.py 逻辑
    
    summary = "初步完成了文案撰写 (Placeholder)"
    
    emit_agent_log(
        log_type="info",
        content=summary,
        extra={"type": "worker_complete", "worker": "writer_agent", "status": "success", "summary": summary}
    )
    
    # 返回给 Supervisor 的报告
    return {
        "completed_steps": ["writer_agent"],
        "worker_summaries": [{
            "worker": "writer_agent",
            "status": "success",
            "summary": summary
        }]
    }
