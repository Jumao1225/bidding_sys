"""ChatAgent 会话、消息和上下文 checkpoint 数据模型。"""

from typing import Any

from sqlalchemy import ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import TenantBase


class ChatSession(TenantBase):
    """保存一个文档下的独立聊天会话及其当前运行配置。"""

    __tablename__ = "chat_sessions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_chat_sessions_tenant_id_id"),
    )

    document_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="当前会话绑定的招标文档ID",
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="新会话", comment="会话标题")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", index=True, comment="会话状态：active、archived、deleted"
    )
    latest_checkpoint_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, comment="最新上下文 checkpoint ID"
    )
    active_provider: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="当前模型提供商")
    active_model: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="当前模型名称")
    context_format_version: Mapped[str] = mapped_column(
        String(50), nullable=False, default="v1", comment="通用上下文格式版本"
    )
    parent_session_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True, comment="分叉来源会话ID"
    )


class ChatMessage(TenantBase):
    """保存会话的原始消息，不因上下文压缩而删除。"""

    __tablename__ = "chat_messages"
    __table_args__ = (
        UniqueConstraint("session_id", "sequence", name="uq_chat_messages_session_sequence"),
    )

    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属会话ID",
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, comment="会话内递增序号")
    role: Mapped[str] = mapped_column(String(20), nullable=False, comment="user、assistant 或 tool")
    content: Mapped[str] = mapped_column(Text, nullable=False, default="", comment="消息内容")
    tool_name: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="工具名称")
    tool_arguments: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, comment="工具调用参数")
    tool_call_id: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="工具调用关联ID")
    provider_payload_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, comment="provider 原始消息字段，仅供同 provider 重放"
    )
    sources_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True, comment="回答引用来源")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="completed", index=True, comment="streaming、completed、failed"
    )
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="已知时保存消息 token 数")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, comment="失败原因")


class ChatContextCheckpoint(TenantBase):
    """保存压缩后的工作上下文，summary 是跨模型默认格式。"""

    __tablename__ = "chat_context_checkpoints"

    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属会话ID",
    )
    upto_sequence: Mapped[int] = mapped_column(Integer, nullable=False, comment="checkpoint 覆盖到的消息序号")
    strategy: Mapped[str] = mapped_column(String(20), nullable=False, default="summary", comment="summary 或 native")
    provider: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="生成 checkpoint 的 provider")
    model: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="生成 checkpoint 的模型")
    protocol: Mapped[str] = mapped_column(
        String(30), nullable=False, default="chat_completions", comment="chat_completions 或 responses"
    )
    capability_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, comment="模型能力快照")
    payload: Mapped[dict[str, Any] | str] = mapped_column(JSON, nullable=False, comment="结构化摘要或 native payload")
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="checkpoint token 数")
    context_format_version: Mapped[str] = mapped_column(
        String(50), nullable=False, default="v1", comment="checkpoint 格式版本"
    )
