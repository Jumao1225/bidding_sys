from loguru import logger
from typing import Dict, Any
from sqlalchemy.orm import Session
from app.agents.state import BiddingState
from app.services.llm_service import llm_service
from app.db.session import SessionLocal
from app.db.crud.document import document_crud
from app.core.audit_decorator import audit_node


def build_master_agent_prompt(document_id: str, toc_str: str) -> str:
    """构建主 Agent 提示词，明确区分业务字段为空和工具执行失败。"""

    # 原文未提供某个字段时返回 null 是合法结果，不能把业务结果状态当成调用失败。
    return f"""
        你是一位顶级的工程招投标分析师。
        
        【标书章节大纲 (文档全貌导航)】:
        {toc_str if toc_str else '暂无大纲'}
        
        【任务要求】
        当前处理的文档 ID 为：{document_id}
        
        你现在拥有 5 个极其强大的垂直领域提取工具（资质、财务、时限、技术工况、评标罚则）。
        
        工作流指示：
        1. 请你自主思考，尽可能**并发（一次性）**调用这 5 个专项工具对标书进行深度结构化剥离。你必须在调用工具时传入 document_id；每个工具在本轮最多调用一次。
        2. 专项工具内部已经做好了数据落盘，你只需要查阅它们返回的 JSON 结果。
        3. 工具首次成功返回结构化结果后，必须直接接受该结果。`null`、空数组、字段缺失、未识别章节、设备明细为 0 或结果不够完整，均可能表示原文没有对应信息，严禁仅因这些数据内容再次调用同一工具。
        4. 只有工具返回明确的执行错误，且错误信息表明是暂时性调用失败时，才允许根据错误信息重试；不得把业务字段内容当成失败依据。
        
        最后，当所有必要的专项提取工具都调用完毕，并且你认为已经尽可能多地提取到了元数据后，请直接回复：“所有专项数据提取完毕”。
        不要输出任何 JSON 数据。
        """


@audit_node(name="MasterAgent")
def master_agent_node(state: BiddingState) -> Dict[str, Any]:
    """
    Master Agent (总控智能体) - 第 1 步
    负责从 DB 拉取解析后的文本，利用大模型提取核心元数据（编号、限价、硬性资质、痛点等）。
    提取结果将落库到 Document.parsed_metadata，供下游 Worker 使用。
    """
    from app.worker.tasks import emit_agent_log
    logger.info("====== [Node] Master Agent Started ======")
    
    task_id = state.get("task_id")
    document_id = state.get("document_id")
    emit_agent_log("info", "启动元数据提取大脑...", extra={"type": "worker_start", "worker": "master_agent"})
    if not document_id:
        logger.error("State 中缺少 document_id，跳过 Master Agent")
        return {"status": "master_failed", "error": "Missing document_id"}

    db: Session = SessionLocal()
    try:
        # 1. 查找对应的 Document 记录
        user_id = state.get("user_id")
        tenant_id = state.get("tenant_id")
        
        from app.core.context import current_user_id, current_tenant_id
        if user_id: current_user_id.set(user_id)
        if tenant_id: current_tenant_id.set(tenant_id)

        document = document_crud.get_document_by_id(db, document_id, user_id, tenant_id)
        if not document:
            return {"status": "master_failed", "error": f"未找到文档记录: {document_id}"}
            
        # 2. [DB First] 从数据库拉取属于该文档的所有解析块
        logger.info("Master Agent: 正在从数据库提取解析文本块...")
        chunks = document_crud.get_document_chunks(db, document_id)
        
        if not chunks:
            logger.warning("该文档没有可用的解析文本块！")
            return {"status": "master_failed", "error": "No parsed chunks found in DB"}
            
        doc_text = "\n\n".join([chunk.content for chunk in chunks])
        
        # 3. 构造 Tool-Calling Agent 提取元数据
        logger.info("Master Agent: 正在初始化 Tool-Calling Agent 并赋予 RAG 检索能力...")
        
        from langgraph.prebuilt import create_react_agent
        from langchain_core.messages import HumanMessage
        from app.agents.tools.metadata_tools import METADATA_TOOLS
        import re
        
        all_tools = METADATA_TOOLS
        
        supervisor_llm = llm_service.get_llm(temperature=0.3, json_mode=False, tenant_id=tenant_id)
        if supervisor_llm is None:
            raise ValueError("当前租户尚未配置可用的大模型")

        logger.info("Master Agent 使用租户 %s 的模型配置初始化 Tool-Calling Agent", tenant_id)
        agent = create_react_agent(supervisor_llm, all_tools)
        
        toc_str = ""
        if document.parsed_metadata and "table_of_contents" in document.parsed_metadata:
            toc_str = document.parsed_metadata["table_of_contents"]
            logger.info(f"--- 提取到的章节大纲 (TOC) ---\n{toc_str}\n----------------------------------")
        else:
            logger.info("--- 未提取到章节大纲 (TOC) ---")
            
        prompt = build_master_agent_prompt(document_id=document_id, toc_str=toc_str)
        logger.info("主 Agent 已启用严格结果接受策略：业务字段为 null 不触发专项工具重试")
        
        logger.info("Master Agent: 开始自主思考并执行 Tool Calling 循环...")
        import time
        start_time = time.time()
        inputs = {"messages": [HumanMessage(content=prompt)]}
        agent_result = agent.invoke(inputs)
        end_time = time.time()
        
        final_message = agent_result["messages"][-1]
        final_text = final_message.content
        logger.info(f"Master Agent 最终原始回复: {final_text}")
        
        # 提取 Token (如果存在)
        prompt_tokens = 0
        completion_tokens = 0
        if hasattr(final_message, 'response_metadata') and 'token_usage' in final_message.response_metadata:
            token_usage = final_message.response_metadata['token_usage']
            prompt_tokens = token_usage.get('prompt_tokens', 0)
            completion_tokens = token_usage.get('completion_tokens', 0)
            
        # 主动将 Master Agent 的 Tool Calling 最终思考与结果写入审计表
        from app.services.audit_service import audit_service
        audit_service.log_event(
            action_type="llm_call",
            inputs={"prompt": prompt},
            outputs={"content": final_text, "full_messages_count": len(agent_result["messages"])},
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            execution_time_ms=int((end_time - start_time) * 1000)
        )

        logger.info("Master Agent: 所有工具调用已结束，纯调度任务完成。")
        
        summary = "成功提取5大元数据"
        emit_agent_log("info", summary, extra={"type": "worker_complete", "worker": "master_agent", "status": "success", "summary": summary, "document_id": document_id})

        return {
            "status": "master_completed",
            "completed_steps": ["master_agent"],
            "worker_summaries": [{
                "worker": "master_agent",
                "status": "success",
                "summary": summary
            }]
        }
        
    except Exception as e:
        db.rollback()
        logger.exception("Master Agent 执行失败")
        emit_agent_log("error", f"提取失败: {str(e)}", extra={"type": "worker_complete", "worker": "master_agent", "status": "failed", "summary": str(e)})
        return {"status": "master_failed", "error": str(e)}
    finally:
        db.close()
