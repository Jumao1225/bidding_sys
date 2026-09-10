"""ChatAgent 会话和原始消息持久化服务。"""

from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from loguru import logger
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models.chat import ChatContextCheckpoint, ChatMessage, ChatSession


class ChatSessionService:
    """封装会话归属校验、消息追加和 checkpoint 持久化。"""

    @staticmethod
    def create_session(
        db: Session,
        tenant_id: str,
        user_id: str,
        document_id: str,
        title: str = "新会话",
        provider: Optional[str] = None,
        model: Optional[str] = None,
        parent_session_id: Optional[str] = None,
    ) -> ChatSession:
        """创建一个租户和用户隔离的独立会话。"""
        session = ChatSession(
            tenant_id=tenant_id,
            user_id=user_id,
            document_id=document_id,
            title=(title or "新会话").strip()[:255],
            active_provider=provider,
            active_model=model,
            parent_session_id=parent_session_id,
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        logger.info("创建 ChatAgent 会话：session_id={}，document_id={}，tenant_id={}", session.id, document_id, tenant_id)
        return session

    @staticmethod
    def get_owned_session(
        db: Session,
        session_id: str,
        tenant_id: str,
        user_id: str,
        document_id: Optional[str] = None,
    ) -> Optional[ChatSession]:
        """按租户、用户和文档校验会话归属，避免仅凭 session_id 越权读取。"""
        query = db.query(ChatSession).filter(
            ChatSession.id == session_id,
            ChatSession.tenant_id == tenant_id,
            ChatSession.user_id == user_id,
            ChatSession.status != "deleted",
        )
        if document_id:
            query = query.filter(ChatSession.document_id == document_id)
        return query.first()

    @staticmethod
    def list_owned_sessions(db: Session, tenant_id: str, user_id: str, document_id: str) -> list[ChatSession]:
        """查询当前用户在指定文档下的会话列表。"""
        return (
            db.query(ChatSession)
            .filter(
                ChatSession.tenant_id == tenant_id,
                ChatSession.user_id == user_id,
                ChatSession.document_id == document_id,
                ChatSession.status != "deleted",
            )
            .order_by(ChatSession.updated_at.desc(), ChatSession.created_at.desc())
            .all()
        )

    @staticmethod
    def update_session(
        db: Session,
        session: ChatSession,
        title: Optional[str] = None,
        status: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> ChatSession:
        """更新会话显示信息和当前模型配置。"""
        if title is not None:
            normalized_title = title.strip()
            if not normalized_title:
                raise ValueError("会话标题不能为空")
            session.title = normalized_title[:255]
        if status is not None:
            if status not in {"active", "archived", "deleted"}:
                raise ValueError("不支持的会话状态")
            session.status = status
        if provider is not None:
            session.active_provider = provider
        if model is not None:
            session.active_model = model
        db.commit()
        db.refresh(session)
        return session

    @staticmethod
    def delete_session(db: Session, session: ChatSession) -> ChatSession:
        """软删除会话，保留原始消息和 checkpoint 供审计使用。"""
        session.status = "deleted"
        db.commit()
        db.refresh(session)
        logger.info("删除 ChatAgent 会话：session_id={}，保留历史消息供审计", session.id)
        return session

    @staticmethod
    def append_message(
        db: Session,
        session: ChatSession,
        role: str,
        content: str = "",
        status: str = "completed",
        tool_name: Optional[str] = None,
        tool_arguments: Optional[dict[str, Any]] = None,
        tool_call_id: Optional[str] = None,
        provider_payload_json: Optional[dict[str, Any]] = None,
        sources_json: Optional[list[dict[str, Any]]] = None,
        token_count: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> ChatMessage:
        """以会话内递增序号追加一条不可变原始消息。"""
        if role not in {"user", "assistant", "tool"}:
            raise ValueError("不支持的消息角色")
        if status not in {"streaming", "completed", "failed"}:
            raise ValueError("不支持的消息状态")

        latest_sequence = db.query(func.max(ChatMessage.sequence)).filter(ChatMessage.session_id == session.id).scalar()
        message = ChatMessage(
            tenant_id=session.tenant_id,
            user_id=session.user_id,
            session_id=session.id,
            sequence=(latest_sequence or 0) + 1,
            role=role,
            content=content or "",
            status=status,
            tool_name=tool_name,
            tool_arguments=tool_arguments,
            tool_call_id=tool_call_id,
            provider_payload_json=provider_payload_json,
            sources_json=sources_json,
            token_count=token_count,
            error_message=error_message,
        )
        db.add(message)
        db.commit()
        db.refresh(message)
        session.updated_at = message.created_at
        db.commit()
        return message

    @staticmethod
    def import_legacy_history(db: Session, session: ChatSession, history: Iterable[Any]) -> int:
        """将旧版前端 history 一次性迁移到服务端会话。"""
        imported_count = 0
        for item in history:
            role = getattr(item, "role", None) if not isinstance(item, dict) else item.get("role")
            content = getattr(item, "content", "") if not isinstance(item, dict) else item.get("content", "")
            normalized_role = "assistant" if role in {"ai", "assistant"} else "user" if role == "user" else None
            if not normalized_role or not str(content or "").strip():
                continue
            ChatSessionService.append_message(
                db=db,
                session=session,
                role=normalized_role,
                content=str(content),
            )
            imported_count += 1
        if imported_count:
            logger.info("迁移旧版聊天历史：session_id={}，消息数={}", session.id, imported_count)
        return imported_count

    @staticmethod
    def list_messages(
        db: Session,
        session: ChatSession,
        after_sequence: int = 0,
    ) -> list[ChatMessage]:
        """按会话序号读取 checkpoint 之后的原始消息。"""
        return (
            db.query(ChatMessage)
            .filter(ChatMessage.session_id == session.id, ChatMessage.sequence > after_sequence)
            .order_by(ChatMessage.sequence.asc())
            .all()
        )

    @staticmethod
    def get_latest_failed_assistant(
        db: Session,
        session: ChatSession,
    ) -> Optional[ChatMessage]:
        """获取会话中最新的失败助手消息，供断点续答使用。"""
        return (
            db.query(ChatMessage)
            .filter(
                ChatMessage.session_id == session.id,
                ChatMessage.role == "assistant",
                ChatMessage.status == "failed",
            )
            .order_by(ChatMessage.sequence.desc())
            .first()
        )

    @staticmethod
    def recover_failed_assistant(
        db: Session,
        session: ChatSession,
        message: ChatMessage,
        content: str,
        provider_payload_json: Optional[dict[str, Any]] = None,
        sources_json: Optional[list[dict[str, Any]]] = None,
    ) -> ChatMessage:
        """将失败助手消息恢复为完成消息，避免续答后在界面产生重复气泡。"""
        if message.status != "failed":
            raise ValueError("只有失败的助手消息可以执行断点续答")

        message.content = content or ""
        message.status = "completed"
        message.provider_payload_json = provider_payload_json
        message.sources_json = sources_json
        message.error_message = None
        session.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(message)
        logger.info("恢复失败助手消息：session_id={}，message_id={}", session.id, message.id)
        return message

    @staticmethod
    def get_latest_checkpoint(db: Session, session: ChatSession) -> Optional[ChatContextCheckpoint]:
        """读取会话最新 checkpoint。"""
        if session.latest_checkpoint_id:
            checkpoint = db.query(ChatContextCheckpoint).filter(
                ChatContextCheckpoint.id == session.latest_checkpoint_id,
                ChatContextCheckpoint.session_id == session.id,
                ChatContextCheckpoint.tenant_id == session.tenant_id,
            ).first()
            if checkpoint:
                return checkpoint
        return (
            db.query(ChatContextCheckpoint)
            .filter(
                ChatContextCheckpoint.session_id == session.id,
                ChatContextCheckpoint.tenant_id == session.tenant_id,
            )
            .order_by(ChatContextCheckpoint.upto_sequence.desc(), ChatContextCheckpoint.created_at.desc())
            .first()
        )

    @staticmethod
    def save_summary_checkpoint(
        db: Session,
        session: ChatSession,
        upto_sequence: int,
        payload: dict[str, Any],
        provider: Optional[str],
        model: Optional[str],
        protocol: str,
        capability_snapshot: Optional[dict[str, Any]],
        token_count: Optional[int] = None,
    ) -> ChatContextCheckpoint:
        """保存通用结构化摘要并更新会话的最新 checkpoint 指针。"""
        checkpoint = ChatContextCheckpoint(
            tenant_id=session.tenant_id,
            user_id=session.user_id,
            session_id=session.id,
            upto_sequence=upto_sequence,
            strategy="summary",
            provider=provider,
            model=model,
            protocol=protocol,
            capability_snapshot=capability_snapshot,
            payload=payload,
            token_count=token_count,
            context_format_version=session.context_format_version,
        )
        db.add(checkpoint)
        db.flush()
        session.latest_checkpoint_id = checkpoint.id
        db.commit()
        db.refresh(checkpoint)
        logger.info("保存 ChatAgent 摘要 checkpoint：session_id={}，upto_sequence={}", session.id, upto_sequence)
        return checkpoint


chat_session_service = ChatSessionService()
