"""
聊天接口端点 (Chat API Endpoint)

提供基于 RAG + SSE 流式输出的智能问答接口，专为前端 ChatPanel 设计。
支持多轮对话历史携带与引文来源追踪。
"""
import json
from typing import AsyncGenerator, Literal
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from loguru import logger

from app.services.rag_service import rag_service
from app.services.llm_service import llm_service

router = APIRouter()


# ==================== 请求/响应 Schema ====================

class ChatMessage(BaseModel):
    """单条对话消息结构"""
    role: Literal["user", "ai"] = Field(..., description="消息角色：user 或 ai")
    content: str = Field(..., description="消息内容")


class ChatRequest(BaseModel):
    """聊天请求体"""
    document_id: str = Field(..., description="当前招标文件的数据库 ID")
    question: str = Field(..., description="用户当前提问")
    history: list[ChatMessage] = Field(
        default_factory=list,
        description="多轮对话历史，最多携带最近 10 条"
    )


# ==================== 核心逻辑 ====================

def _build_system_prompt(rag_context: str) -> str:
    """
    构建系统提示词，注入 RAG 检索结果与引文标记要求。
    要求模型在引用文档关键数据后附加引文标记 [来源: 章节名]。
    """
    return f"""你是一位资深的招投标领域专家助手，已深度阅读了当前的招标文件。
你的任务是基于下方检索到的【文档原文上下文】，精准、专业地回答用户的问题。

【行为准则】
1. 宁缺毋滥：所有回答必须有文档依据，不可凭空推断或编造数据。
2. 引文标记：在引用文档中的关键数据或条款时，必须在句尾附加 [来源: 章节名] 格式的引文标记，例如：
   "投标保证金为合同总价的 5% [来源: 第三章 投标须知]"
3. 格式规范：使用 Markdown 格式输出，重要数据可加粗，复杂信息可用列表或表格。
4. 如果问题超出文档范围，诚实告知并建议用户查阅相关章节。

【文档检索上下文】
{rag_context}
"""


def _build_chat_messages(system_prompt: str, history: list[ChatMessage], question: str) -> list:
    """
    将系统提示词、历史记录和当前问题组装为 LangChain 消息格式。
    历史记录最多取最近 10 条以控制 Token 消耗。
    """
    from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

    messages = [SystemMessage(content=system_prompt)]

    # 最多携带最近 10 条历史消息，防止 Token 超限
    recent_history = history[-10:] if len(history) > 10 else history
    for msg in recent_history:
        if msg.role == "user":
            messages.append(HumanMessage(content=msg.content))
        else:
            messages.append(AIMessage(content=msg.content))

    # 追加当前提问
    messages.append(HumanMessage(content=question))
    return messages


def _get_rag_sources(document_id: str, query: str, top_k: int = 5) -> list[dict]:
    """
    从数据库检索 RAG 结果，返回前端可展示的引文来源列表。
    每条包含 section_title 和 text_preview（前200字）。
    不同于 rag_service 返回的拼接文本，此处保留各切片的元数据结构。
    """
    try:
        from app.db.session import SessionLocal
        from app.db.models.project import DocChunk
        from sqlalchemy.orm import Session

        # 生成查询向量
        query_embeddings = llm_service.generate_embeddings([query])
        if not query_embeddings:
            return []

        db: Session = SessionLocal()
        try:
            # 向量相似度检索，返回最相近的 top_k 条
            results = (
                db.query(DocChunk)
                .filter(DocChunk.document_id == document_id)
                .order_by(DocChunk.embedding.cosine_distance(query_embeddings[0]))
                .limit(top_k)
                .all()
            )
            sources = []
            seen_sections: set[str] = set()
            for chunk in results:
                sec = chunk.section_title or "未知章节"
                # 同一章节只保留一条预览，避免重复展示
                if sec not in seen_sections:
                    sources.append({
                        "section_title": sec,
                        "text_preview": chunk.content[:200] if chunk.content else ""
                    })
                    seen_sections.add(sec)
            return sources
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"获取 RAG 来源切片失败，降级返回空列表: {str(e)}")
        return []


async def _stream_rag_chat(
    document_id: str,
    question: str,
    history: list[ChatMessage]
) -> AsyncGenerator[str, None]:
    """
    核心流式聊天生成器：
    1. RAG 检索召回相关切片（附带 section_title 元数据）
    2. 构建包含引文要求的 System Prompt
    3. 通过 LLM astream() 逐 token 推送 SSE 事件
    4. 流结束后推送 done 事件（附带 RAG 来源切片供前端渲染引文 Badge）
    """
    # --- Step 1: RAG 检索上下文 ---
    logger.info(
        f"ChatPanel RAG 检索启动，文档ID: {document_id}，"
        f"问题: {question[:50]}..."
    )
    try:
        rag_context = rag_service.search_bidding_document(
            document_id=document_id,
            query=question,
            top_k=5,
            context_mode="chapter"
        )
        # 独立获取带元数据的引文来源列表
        sources = _get_rag_sources(document_id=document_id, query=question, top_k=5)
    except Exception as e:
        logger.error(f"RAG 检索失败，降级为无上下文模式: {str(e)}")
        rag_context = "（当前文档检索暂时不可用，请根据通用知识作答，并明确说明无法定位原文）"
        sources = []

    # --- Step 2: 构建 LangChain 消息链 ---
    system_prompt = _build_system_prompt(rag_context)
    messages = _build_chat_messages(system_prompt, history, question)

    # --- Step 3: 流式推送 token ---
    logger.info("ChatPanel LLM 流式输出启动...")
    try:
        async for token in llm_service.astream_chat(messages, temperature=0.7):
            # SSE 标准格式：data: {...}\n\n
            event_data = json.dumps(
                {"type": "token", "content": token},
                ensure_ascii=False
            )
            yield f"data: {event_data}\n\n"
    except Exception as e:
        logger.error(f"LLM 流式输出异常: {str(e)}")
        error_data = json.dumps(
            {"type": "error", "content": f"AI 回复出现异常，请稍后重试: {str(e)}"},
            ensure_ascii=False
        )
        yield f"data: {error_data}\n\n"
        return

    # --- Step 4: 推送结束事件（附带引文来源） ---
    done_data = json.dumps(
        {"type": "done", "sources": sources},
        ensure_ascii=False
    )
    yield f"data: {done_data}\n\n"
    logger.info(f"ChatPanel 流式问答完成，来源切片数: {len(sources)}")


# ==================== 路由定义 ====================

@router.post("/")
async def chat_stream(request: ChatRequest):
    """
    流式聊天接口 (SSE)。

    接收用户问题和对话历史，执行 RAG 检索后通过 StreamingResponse 流式返回 AI 回复。

    SSE 事件类型：
    - {\"type\": \"token\", \"content\": \"逐字内容\"}   -- 逐 token 推送
    - {\"type\": \"done\", \"sources\": [...]}          -- 完成，附带引文来源
    - {\"type\": \"error\", \"content\": \"错误信息\"}    -- 异常情况
    """
    # 前置参数校验（Early Return）
    if not request.document_id:
        raise HTTPException(status_code=400, detail="document_id 为必填项")
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="question 不能为空")

    logger.info(
        f"ChatPanel 收到聊天请求，文档ID: {request.document_id}，"
        f"问题: {request.question[:50]}，历史轮数: {len(request.history)}"
    )

    return StreamingResponse(
        _stream_rag_chat(
            document_id=request.document_id,
            question=request.question,
            history=request.history
        ),
        media_type="text/event-stream",
        headers={
            # 禁用响应缓冲，确保每个 token 立即推送到客户端
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )
