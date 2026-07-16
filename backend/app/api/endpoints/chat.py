"""
聊天接口端点 (Chat API Endpoint)

提供基于 RAG + SSE 流式输出的智能问答接口，专为前端 ChatPanel 设计。
支持多轮对话历史携带与引文来源追踪。
"""
from typing import Literal
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agents.chat_agent import chat_agent

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

# ==================== 路由定义 ====================

@router.post("/")
async def chat_stream(request: ChatRequest):
    """
    流式聊天接口 (SSE)。

    接收用户问题和对话历史，交由 ChatAgent 进行自主多步规划与工具调用。
    """
    if not request.document_id:
        raise HTTPException(status_code=400, detail="document_id 为必填项")
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="question 不能为空")

    return StreamingResponse(
        chat_agent.stream_chat(
            document_id=request.document_id,
            question=request.question,
            history=request.history
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )
