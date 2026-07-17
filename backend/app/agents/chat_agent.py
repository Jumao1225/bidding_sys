import json
import uuid
import time
from typing import AsyncGenerator
from loguru import logger
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from app.services.llm_service import llm_service
from app.services.rag_service import rag_service
from app.services.audit_service import audit_service
from app.core.context import current_task_id, current_node_name
from app.agents.tools.metadata_tools import METADATA_TOOLS
from app.agents.tools.rag_tools import search_bidding_document

class ChatAgent:
    """
    负责前台 ChatPanel 对话的 Agent。
    集成 ReAct 机制，能够自主调用专项结构化提取工具或后备语义检索工具，
    提供带有引文标记与来源溯源 (Sources) 的流式回答。
    """
    
    def _build_chat_system_prompt(self, document_id: str) -> str:
        return f"""你是一位资深的工程招投标领域专家助手（ChatAgent），已接入当前招标文件数据库。
【能力说明】
你可以自主调用各种专项提取工具（如资质、财务、时限、工况、罚则等）来查询已被系统结构化提取的关键数据。
如果专项工具查不到，你可以使用 search_bidding_document 工具在原文档中进行语义检索。

【行为准则】
1. 宁缺毋滥：所有回答必须有文档依据，不可凭空推断或编造数据。
2. 主动探索：遇到需要查询的数据，优先思考调用相应的提取工具获取。
3. 应对质疑与纠错：当用户指出你之前回答错误，或指出某两个概念不同（如“A和B不是一个东西”）时，你**必须**调用 search_bidding_document 工具在原文中重新进行检索。**警告：你必须真正地触发系统级工具调用（发出 tool_call 指令），绝对不能仅仅在文本里骗用户说“我来检索原文”然后凭记忆胡编乱造！**
4. 格式规范：使用 Markdown 格式输出，重要数据可加粗，复杂信息可用列表或表格。

当前处理的文档ID: {document_id}。调用工具时请直接传入该ID。
"""

    async def stream_chat(
        self,
        document_id: str,
        question: str,
        history: list
    ) -> AsyncGenerator[str, None]:
        """
        流式聊天生成器 (ReAct Agent 架构)：
        1. 初始化 Tool-Calling Agent
        2. 使用 astream_events 拦截 on_tool_start 和 on_chat_model_stream
        3. 将工具调用记录推送到前端并写入 Audit 数据库
        4. 收集所有查询词，最后合并引文来源
        """
        chat_task_id = f"chat-{uuid.uuid4().hex[:8]}"
        current_task_id.set(chat_task_id)
        current_node_name.set("ChatAgent")

        logger.info(
            f"ChatAgent 会话启动，任务ID: {chat_task_id}，文档ID: {document_id}，问题: {question[:50]}..."
        )

        all_tools = METADATA_TOOLS + [search_bidding_document]
        agent = create_react_agent(llm_service.raw_llm, all_tools)

        system_prompt = self._build_chat_system_prompt(document_id)
        
        messages = [SystemMessage(content=system_prompt)]
        
        # history 是 ChatMessage 对象列表，需要提取
        recent_history = history[-10:] if len(history) > 10 else history
        for msg in recent_history:
            if getattr(msg, "role", None) == "user" or (isinstance(msg, dict) and msg.get("role") == "user"):
                content = getattr(msg, "content", "") or (isinstance(msg, dict) and msg.get("content", ""))
                messages.append(HumanMessage(content=content))
            else:
                content = getattr(msg, "content", "") or (isinstance(msg, dict) and msg.get("content", ""))
                messages.append(AIMessage(content=content))
                
        messages.append(HumanMessage(content=question))

        # 收集 Agent 实际检索的关键词，以便最后生成引文来源
        agent_search_queries = set()

        try:
            async for event in agent.astream_events({"messages": messages}, version="v2"):
                kind = event["event"]
                
                if kind == "on_chat_model_stream":
                    chunk = event["data"]["chunk"]
                    if chunk.content:
                        event_data = json.dumps(
                            {"type": "token", "content": chunk.content},
                            ensure_ascii=False
                        )
                        yield f"data: {event_data}\n\n"
                        
                elif kind == "on_tool_start":
                    tool_name = event["name"]
                    tool_inputs = event["data"].get("input", {})
                    
                    # 记录可能用于搜索的关键词
                    if "search_keywords" in tool_inputs:
                        agent_search_queries.add(tool_inputs["search_keywords"])
                    if "query" in tool_inputs:
                        agent_search_queries.add(tool_inputs["query"])
                    
                    audit_service.log_event(
                        action_type="tool_call",
                        inputs={"tool_name": tool_name, "args": tool_inputs},
                        outputs={"status": "started"},
                        status="success"
                    )
                    
                    tool_desc_map = {
                        "extract_qualification_info": "查询项目资质要求",
                        "extract_financial_info": "查询财务与资金条件",
                        "extract_timeline_info": "查询商务时限要求",
                        "extract_engineering_info": "查询技术与工况要求",
                        "extract_evaluation_info": "查询评标办法与罚则",
                        "search_bidding_document": "在标书原文中检索细节"
                    }
                    friendly_name = tool_desc_map.get(tool_name, tool_name)
                    
                    msg_content = f"正在{friendly_name}...\n`{tool_name}({json.dumps(tool_inputs, ensure_ascii=False)})`"
                    tool_data = json.dumps(
                        {"type": "tool_call", "content": msg_content},
                        ensure_ascii=False
                    )
                    yield f"data: {tool_data}\n\n"
                    
        except Exception as e:
            logger.error(f"ChatAgent 流式输出异常: {str(e)}")
            error_data = json.dumps(
                {"type": "error", "content": f"AI 回复出现异常，请稍后重试: {str(e)}"},
                ensure_ascii=False
            )
            yield f"data: {error_data}\n\n"
            return

        # --- Step 4: 汇总引文来源并推送结束事件 ---
        final_sources = []
        seen_sections = set()
        
        # 如果 Agent 没调用任何检索工具，拿用户的原始问题当做兜底检索词去获取一次引文
        if not agent_search_queries:
            agent_search_queries.add(question)
            
        # 对所有收集到的关键词执行 RAG 溯源（控制总切片数，避免过多）
        for q in list(agent_search_queries)[:3]:  # 最多取前 3 个查询词，避免引文爆炸
            sub_sources = rag_service.get_rag_sources_for_citations(document_id=document_id, query=q, top_k=2)
            for s in sub_sources:
                if s["section_title"] not in seen_sections:
                    final_sources.append(s)
                    seen_sections.add(s["section_title"])

        done_data = json.dumps(
            {"type": "done", "sources": final_sources},
            ensure_ascii=False
        )
        yield f"data: {done_data}\n\n"
        logger.info(f"ChatAgent 流式问答完成，引文数: {len(final_sources)}")

chat_agent = ChatAgent()
