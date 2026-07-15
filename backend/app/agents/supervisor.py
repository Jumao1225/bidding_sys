import logging
import json
from typing import Dict, Any
from sqlalchemy.orm import Session
from app.agents.state import BiddingState
from app.services.llm_service import llm_service
from app.db.session import SessionLocal
from app.db.models.project import Document, DocChunk
from app.core.audit_decorator import audit_node

logger = logging.getLogger(__name__)

@audit_node(name="MasterAgent")
def master_agent_node(state: BiddingState) -> Dict[str, Any]:
    """
    Master Agent (总控智能体) - 第 1 步
    负责从 DB 拉取解析后的文本，利用大模型提取核心元数据（编号、限价、硬性资质、痛点等）。
    提取结果将落库到 Document.parsed_metadata，供下游 Worker 使用。
    """
    logger.info("--- 启动 Master Agent ---")
    
    document_id = state.get("document_id")
    if not document_id:
        logger.error("State 中缺少 document_id，跳过 Master Agent")
        return {"status": "master_failed", "error": "Missing document_id"}

    db: Session = SessionLocal()
    try:
        # 1. 查找对应的 Document 记录
        document = db.query(Document).filter(Document.id == document_id).first()
        if not document:
            return {"status": "master_failed", "error": f"未找到文档记录: {document_id}"}
            
        # 2. [DB First] 从数据库拉取属于该文档的所有解析块
        logger.info("Master Agent: 正在从数据库提取解析文本块...")
        chunks = db.query(DocChunk).filter(DocChunk.document_id == document_id).order_by(DocChunk.chunk_index).all()
        
        if not chunks:
            logger.warning("该文档没有可用的解析文本块！")
            return {"status": "master_failed", "error": "No parsed chunks found in DB"}
            
        doc_text = "\n\n".join([chunk.content for chunk in chunks])
        
        # 3. 构造 Tool-Calling Agent 提取元数据
        logger.info("Master Agent: 正在初始化 Tool-Calling Agent 并赋予 RAG 检索能力...")
        
        from langgraph.prebuilt import create_react_agent
        from langchain_core.messages import HumanMessage
        from app.agents.tools.metadata_tools import METADATA_TOOLS
        from app.agents.tools.rag_tools import search_bidding_document
        import re
        
        all_tools = METADATA_TOOLS + [search_bidding_document]
        
        if not hasattr(llm_service, 'raw_llm'):
            raise Exception("llm_service 尚未暴露出支持 Tool Calling 的 raw_llm，请检查初始化。")
            
        agent = create_react_agent(llm_service.raw_llm, all_tools)
        
        toc_str = ""
        if document.parsed_metadata and "table_of_contents" in document.parsed_metadata:
            toc_str = document.parsed_metadata["table_of_contents"]
            
        prompt = f"""
        你是一位顶级的工程招投标分析师。
        
        【标书章节大纲 (文档全貌导航)】:
        {toc_str if toc_str else '暂无大纲'}
        
        【标书头部内容 (前25000字)】:
        {doc_text[:25000]}
        
        【任务要求】
        当前处理的文档 ID 为：{document_id}
        
        你现在拥有 5 个极其强大的垂直领域提取工具（资质、财务、时限、技术工况、评标罚则）以及 1 个通用兜底的 RAG 检索工具（search_bidding_document）。
        
        工作流指示：
        1. 请你自主思考，**逐一**调用这 5 个专项工具对标书进行深度结构化剥离。你必须在调用工具时传入 document_id。
        2. 专项工具内部已经做好了数据落盘，你只需要查阅它们返回的 JSON 结果。
        3. 如果工具返回的结果不理想，或者你需要挖掘非标准的“痛点工况”时，请灵活调用 `search_bidding_document` 去靶向检索。
        
        【🚨 强制纠错机制 (Self-Correction) 与刹车边界】
        如果你调用专项提取工具后，查阅返回的 JSON 结果发现**存在核心字段为 null**（例如 budget, max_price_limit 等），说明默认关键词未能命中目标文本。
        你必须**自主更换更丰富或更靶向的同义词**（作为 search_keywords），并**再次调用该提取工具**进行重试。
        但是，必须严格遵守以下“刹车”限制：
        1. **业务刹车**：如果某个字段返回的值是 `"明确无要求"` 或 `"待定"`，这说明原文已明确交代，**绝对禁止重试**，请直接接受该结果。
        2. **物理刹车**：对于同一个提取工具，**最多只能主动重试 2 次**（算上初始调用，合计不超过 3 次）。如果连续 3 次不同的检索词都返回 `null`，说明标书中压根不存在该信息，你必须**接受 null 并放弃重试**，继续推进下一步。
        
        最后综合你所有工具看到的数据，提取以下 4 个核心元数据作为最终总结：
        1. project_number: 项目编号 (例如: SZDZ-2026-NG008号，找不到请填 null)
        2. budget_limit: 上限控制价/预算限价 (请提取纯数字，例如 1181380，找不到填 null)
        3. hard_qualifications: 数组，列出明确要求的硬性企业资质
        4. pain_points: 数组，列出特殊的、施工难度大的痛点工况。
        
        【输出格式】
        请务必在最终回复中，仅输出严格的 JSON 格式数据（包含上述 4 个字段），不要输出任何多余的标记或解释文本，以便程序直接 json.loads 解析。
        """
        
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

        
        match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', final_text, re.DOTALL)
        if match:
            json_str = match.group(1)
        else:
            json_str = final_text
            
        metadata_json = json.loads(json_str)
        logger.info(f"Master Agent 解析成功: {json.dumps(metadata_json, ensure_ascii=False)}")
        
        # 4. [DB First] 提取结果落库，使用 flag_modified 安全更新 JSONB 列并及时提交
        from sqlalchemy.orm.attributes import flag_modified
        doc_in_db = db.query(Document).filter(Document.id == document_id).first()
        if not doc_in_db:
            return {"status": "master_failed", "error": f"文档 {document_id} 在事务提交前不存在"}

        existing_meta = dict(doc_in_db.parsed_metadata or {})
        existing_meta.update(metadata_json)
        doc_in_db.parsed_metadata = existing_meta
        flag_modified(doc_in_db, "parsed_metadata")
        
        db.commit()
        logger.info("Master Agent: 元数据已成功存入 Document.parsed_metadata")
        
        return {
            "status": "master_completed"
        }
        
    except Exception as e:
        db.rollback()
        logger.exception("Master Agent 执行失败")
        return {"status": "master_failed", "error": str(e)}
    finally:
        db.close()
