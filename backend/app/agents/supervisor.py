import logging
import json
from typing import Dict, Any
from sqlalchemy.orm import Session
from app.agents.state import BiddingState
from app.services.llm_service import llm_service
from app.db.session import SessionLocal
from app.db.models.project import Document, DocChunk

logger = logging.getLogger(__name__)

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
        chunks = db.query(DocChunk).filter(DocChunk.document_id == document_id).order_by(DocChunk.created_at).all()
        
        if not chunks:
            logger.warning("该文档没有可用的解析文本块！")
            return {"status": "master_failed", "error": "No parsed chunks found in DB"}
            
        doc_text = "\n\n".join([chunk.content for chunk in chunks])
        
        # 3. 构造 Tool-Calling Agent 提取元数据
        logger.info("Master Agent: 正在初始化 Tool-Calling Agent 并赋予 RAG 检索能力...")
        
        from langgraph.prebuilt import create_react_agent
        from langchain_core.messages import HumanMessage
        from app.skills.document_skills import get_search_tool
        import re
        
        search_tool = get_search_tool(document_id)
        
        if not hasattr(llm_service, 'raw_llm'):
            raise Exception("llm_service 尚未暴露出支持 Tool Calling 的 raw_llm，请检查初始化。")
            
        agent = create_react_agent(llm_service.raw_llm, [search_tool])
        
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
        请提取以下 4 个核心元数据：
        1. project_number: 项目编号 (例如: SZDZ-2026-NG008号，找不到请填 null)
        2. budget_limit: 上限控制价/预算限价 (请提取纯数字，例如 1181380，找不到填 null)
        3. hard_qualifications: 数组，列出明确要求的硬性企业资质
        4. pain_points: 数组，列出特殊的、施工难度大的痛点工况。请务必结合【标书章节大纲】自主调用 `search_document_tool` 工具（例如针对“技术规范”、“施工说明”等特定章节）搜索“施工难点”或“特殊工况”去查询标书后续内容。必须将痛点描述和检索结果中的“来源章节”、“页码”合并为一个字符串，例如 ["必须跨越220kV高压线 (来源章节: 第七章 技术规范, 第 45 页)"]
        
        【输出格式】
        请务必在最终回复中，仅输出严格的 JSON 格式数据（包含上述 4 个字段），不要输出任何多余的标记或解释文本，以便程序直接 json.loads 解析。
        """
        
        logger.info("Master Agent: 开始自主思考并执行 Tool Calling 循环...")
        inputs = {"messages": [HumanMessage(content=prompt)]}
        agent_result = agent.invoke(inputs)
        
        final_text = agent_result["messages"][-1].content
        logger.info(f"Master Agent 最终原始回复: {final_text}")
        
        match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', final_text, re.DOTALL)
        if match:
            json_str = match.group(1)
        else:
            json_str = final_text
            
        metadata_json = json.loads(json_str)
        logger.info(f"Master Agent 解析成功: {json.dumps(metadata_json, ensure_ascii=False)}")
        
        # 4. [DB First] 提取结果落库，注意保留原有的 metadata (如 table_of_contents)
        existing_meta = document.parsed_metadata or {}
        new_meta = dict(existing_meta)
        new_meta.update(metadata_json)
        document.parsed_metadata = new_meta
        
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
