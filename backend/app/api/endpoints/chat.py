"""ChatAgent 会话管理和 SSE 聊天接口。"""

from collections.abc import Generator
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents.chat_agent import chat_agent
from app.api import deps
from app.db.crud.document import document_crud
from app.db.models.chat import ChatSession
from app.db.models.project import Document
from app.db.models.user import User
from app.schemas.response.common import success_response
from app.services.chat_session_service import chat_session_service

router = APIRouter()


def get_db() -> Generator[Session, None, None]:
    """为聊天接口提供独立数据库会话。"""
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class ChatMessage(BaseModel):
    """兼容旧版前端的单条对话消息。"""

    role: Literal["user", "ai", "assistant"] = Field(..., description="消息角色")
    content: str = Field(..., description="消息内容")


class ChatRequest(BaseModel):
    """国内模型 Chat Completions 路径的聊天请求。"""

    document_id: str = Field(..., description="当前招标文件的数据库 ID")
    question: str = Field(..., description="用户当前提问")
    session_id: Optional[str] = Field(default=None, description="稳定的会话 ID；首次请求可以为空")
    history: list[ChatMessage] = Field(
        default_factory=list,
        description="旧版前端迁移历史的兼容字段；已有 session_id 时后端忽略",
    )


class ChatSessionCreateRequest(BaseModel):
    """创建会话请求。"""

    document_id: str = Field(..., description="当前招标文件的数据库 ID")
    title: Optional[str] = Field(default=None, max_length=255, description="会话标题")
    history: list[ChatMessage] = Field(default_factory=list, description="旧版 localStorage 历史迁移数据")


class ChatSessionUpdateRequest(BaseModel):
    """更新会话请求。"""

    title: Optional[str] = Field(default=None, max_length=255, description="会话标题")
    status: Optional[Literal["active", "archived"]] = Field(default=None, description="会话状态")


def _serialize_session(session: ChatSession) -> dict[str, object]:
    """将数据库会话转换为统一 API 数据。"""
    return {
        "id": session.id,
        "document_id": session.document_id,
        "title": session.title,
        "status": session.status,
        "active_provider": session.active_provider,
        "active_model": session.active_model,
        "context_format_version": session.context_format_version,
        "parent_session_id": session.parent_session_id,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "updated_at": session.updated_at.isoformat() if session.updated_at else None,
    }


def _validate_document(db: Session, document_id: str, current_user: User) -> Document:
    """校验当前用户对文档的访问权限。"""
    if not document_id:
        raise HTTPException(status_code=400, detail="document_id 为必填项")
    document = document_crud.get_document_by_id(
        db,
        document_id,
        current_user.id,
        current_user.tenant_id,
    )
    if not document:
        raise HTTPException(status_code=403, detail="无权访问此文档或文档不存在")
    return document


@router.post("/sessions")
def create_chat_session(
    request: ChatSessionCreateRequest,
    current_user: User = Depends(deps.get_current_active_user),
    db: Session = Depends(get_db),
):
    """创建当前文档下的独立会话，并支持一次性迁移旧版 history。"""
    _validate_document(db, request.document_id, current_user)
    session = chat_session_service.create_session(
        db=db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        document_id=request.document_id,
        title=request.title or "新会话",
    )
    if request.history:
        chat_session_service.import_legacy_history(db, session, request.history)
    return success_response(_serialize_session(session), message="会话创建成功")


@router.get("/sessions")
def list_chat_sessions(
    document_id: str,
    current_user: User = Depends(deps.get_current_active_user),
    db: Session = Depends(get_db),
):
    """查询当前用户在指定文档下的会话列表。"""
    _validate_document(db, document_id, current_user)
    sessions = chat_session_service.list_owned_sessions(
        db=db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        document_id=document_id,
    )
    return success_response([_serialize_session(session) for session in sessions])


@router.get("/sessions/{session_id}/messages")
def list_chat_messages(
    session_id: str,
    current_user: User = Depends(deps.get_current_active_user),
    db: Session = Depends(get_db),
):
    """读取当前用户会话的原始消息。"""
    session = chat_session_service.get_owned_session(
        db=db,
        session_id=session_id,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
    )
    if session is None:
        raise HTTPException(status_code=403, detail="无权访问此会话或会话不存在")
    messages = chat_session_service.list_messages(db, session)
    data = [
        {
            "id": message.id,
            "sequence": message.sequence,
            "role": "ai" if message.role == "assistant" else message.role,
            "content": message.content,
            "sources": message.sources_json or [],
            # 仅返回工具名称、状态和短结果摘要，避免把 provider 原始请求或大段原文暴露给前端。
            "tool_calls": [
                {
                    "tool_name": item.get("tool_name", ""),
                    "status": item.get("status", "completed"),
                    "output_preview": item.get("output_preview", ""),
                }
                for item in (message.provider_payload_json or {}).get("tool_calls", [])
                if isinstance(item, dict)
            ] if message.role == "assistant" else [],
            "status": message.status,
            "created_at": message.created_at.isoformat() if message.created_at else None,
        }
        for message in messages
    ]
    return success_response(data)


@router.post("/sessions/{session_id}/resume")
async def resume_chat(
    session_id: str,
    current_user: User = Depends(deps.get_current_active_user),
    db: Session = Depends(get_db),
):
    """基于最近一次失败回答已完成的工具结果继续生成，不重复执行工具。"""
    session = chat_session_service.get_owned_session(
        db=db,
        session_id=session_id,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
    )
    if session is None:
        raise HTTPException(status_code=403, detail="无权访问此会话或会话不存在")

    return StreamingResponse(
        chat_agent.resume_failed_chat(
            document_id=session.document_id,
            session_id=session.id,
            user_id=current_user.id,
            tenant_id=current_user.tenant_id,
            db=db,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.patch("/sessions/{session_id}")
def update_chat_session(
    session_id: str,
    request: ChatSessionUpdateRequest,
    current_user: User = Depends(deps.get_current_active_user),
    db: Session = Depends(get_db),
):
    """更新会话标题或归档状态。"""
    session = chat_session_service.get_owned_session(
        db=db,
        session_id=session_id,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
    )
    if session is None:
        raise HTTPException(status_code=403, detail="无权访问此会话或会话不存在")
    try:
        updated = chat_session_service.update_session(
            db=db,
            session=session,
            title=request.title,
            status=request.status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return success_response(_serialize_session(updated), message="会话更新成功")


@router.delete("/sessions/{session_id}")
def delete_chat_session(
    session_id: str,
    current_user: User = Depends(deps.get_current_active_user),
    db: Session = Depends(get_db),
):
    """软删除当前用户的会话，不物理清除消息和上下文 checkpoint。"""
    session = chat_session_service.get_owned_session(
        db=db,
        session_id=session_id,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
    )
    if session is None:
        raise HTTPException(status_code=403, detail="无权访问此会话或会话不存在")
    deleted = chat_session_service.delete_session(db=db, session=session)
    return success_response(_serialize_session(deleted), message="会话已删除")


@router.post("/sessions/{session_id}/archive")
def archive_chat_session(
    session_id: str,
    current_user: User = Depends(deps.get_current_active_user),
    db: Session = Depends(get_db),
):
    """归档当前用户的指定会话。"""
    session = chat_session_service.get_owned_session(
        db=db,
        session_id=session_id,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
    )
    if session is None:
        raise HTTPException(status_code=403, detail="无权访问此会话或会话不存在")
    updated = chat_session_service.update_session(db=db, session=session, status="archived")
    return success_response(_serialize_session(updated), message="会话已归档")


@router.post("/")
async def chat_stream(
    request: ChatRequest,
    current_user: User = Depends(deps.get_current_active_user),
    db: Session = Depends(get_db),
):
    """校验会话后启动基于 LangGraph 和国内模型 API 的 SSE 流式聊天。"""
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="question 不能为空")
    _validate_document(db, request.document_id, current_user)

    if request.session_id:
        session = chat_session_service.get_owned_session(
            db=db,
            session_id=request.session_id,
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            document_id=request.document_id,
        )
        if session is None:
            raise HTTPException(status_code=403, detail="无权访问此会话或会话不属于当前文档")
    else:
        session = chat_session_service.create_session(
            db=db,
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            document_id=request.document_id,
            title=request.question.strip()[:30],
        )
        if request.history:
            chat_session_service.import_legacy_history(db, session, request.history)

    return StreamingResponse(
        chat_agent.stream_chat(
            document_id=request.document_id,
            question=request.question,
            history=request.history,
            user_id=current_user.id,
            tenant_id=current_user.tenant_id,
            session_id=session.id,
            db=db,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
