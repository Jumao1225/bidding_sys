"""新增 ChatAgent 会话、原始消息和上下文 checkpoint 表。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, Sequence[str], None] = "f4c5d6e7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建会话持久化和上下文压缩所需的数据表。"""
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False, comment="租户ID"),
        sa.Column("user_id", sa.String(length=36), nullable=True, comment="创建者用户ID"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False, comment="当前会话绑定的招标文档ID"),
        sa.Column("title", sa.String(length=255), nullable=False, comment="会话标题"),
        sa.Column("status", sa.String(length=20), nullable=False, comment="会话状态"),
        sa.Column("latest_checkpoint_id", sa.String(length=36), nullable=True, comment="最新上下文 checkpoint ID"),
        sa.Column("active_provider", sa.String(length=100), nullable=True, comment="当前模型提供商"),
        sa.Column("active_model", sa.String(length=255), nullable=True, comment="当前模型名称"),
        sa.Column("context_format_version", sa.String(length=50), nullable=False, comment="通用上下文格式版本"),
        sa.Column("parent_session_id", sa.String(length=36), nullable=True, comment="分叉来源会话ID"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_chat_sessions_tenant_id_id"),
    )
    op.create_index("ix_chat_sessions_tenant_id", "chat_sessions", ["tenant_id"], unique=False)
    op.create_index("ix_chat_sessions_user_id", "chat_sessions", ["user_id"], unique=False)
    op.create_index("ix_chat_sessions_document_id", "chat_sessions", ["document_id"], unique=False)
    op.create_index("ix_chat_sessions_status", "chat_sessions", ["status"], unique=False)
    op.create_index("ix_chat_sessions_parent_session_id", "chat_sessions", ["parent_session_id"], unique=False)

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False, comment="租户ID"),
        sa.Column("user_id", sa.String(length=36), nullable=True, comment="创建者用户ID"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False, comment="所属会话ID"),
        sa.Column("sequence", sa.Integer(), nullable=False, comment="会话内递增序号"),
        sa.Column("role", sa.String(length=20), nullable=False, comment="user、assistant 或 tool"),
        sa.Column("content", sa.Text(), nullable=False, comment="消息内容"),
        sa.Column("tool_name", sa.String(length=255), nullable=True, comment="工具名称"),
        sa.Column("tool_arguments", sa.JSON(), nullable=True, comment="工具调用参数"),
        sa.Column("tool_call_id", sa.String(length=255), nullable=True, comment="工具调用关联ID"),
        sa.Column("provider_payload_json", sa.JSON(), nullable=True, comment="provider 原始消息字段"),
        sa.Column("sources_json", sa.JSON(), nullable=True, comment="回答引用来源"),
        sa.Column("status", sa.String(length=20), nullable=False, comment="streaming、completed、failed"),
        sa.Column("token_count", sa.Integer(), nullable=True, comment="已知时保存消息 token 数"),
        sa.Column("error_message", sa.Text(), nullable=True, comment="失败原因"),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "sequence", name="uq_chat_messages_session_sequence"),
    )
    op.create_index("ix_chat_messages_tenant_id", "chat_messages", ["tenant_id"], unique=False)
    op.create_index("ix_chat_messages_user_id", "chat_messages", ["user_id"], unique=False)
    op.create_index("ix_chat_messages_session_id", "chat_messages", ["session_id"], unique=False)
    op.create_index("ix_chat_messages_status", "chat_messages", ["status"], unique=False)

    op.create_table(
        "chat_context_checkpoints",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False, comment="租户ID"),
        sa.Column("user_id", sa.String(length=36), nullable=True, comment="创建者用户ID"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False, comment="所属会话ID"),
        sa.Column("upto_sequence", sa.Integer(), nullable=False, comment="checkpoint 覆盖到的消息序号"),
        sa.Column("strategy", sa.String(length=20), nullable=False, comment="summary 或 native"),
        sa.Column("provider", sa.String(length=100), nullable=True, comment="生成 checkpoint 的 provider"),
        sa.Column("model", sa.String(length=255), nullable=True, comment="生成 checkpoint 的模型"),
        sa.Column("protocol", sa.String(length=30), nullable=False, comment="chat_completions 或 responses"),
        sa.Column("capability_snapshot", sa.JSON(), nullable=True, comment="模型能力快照"),
        sa.Column("payload", sa.JSON(), nullable=False, comment="结构化摘要或 native payload"),
        sa.Column("token_count", sa.Integer(), nullable=True, comment="checkpoint token 数"),
        sa.Column("context_format_version", sa.String(length=50), nullable=False, comment="checkpoint 格式版本"),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_context_checkpoints_tenant_id", "chat_context_checkpoints", ["tenant_id"], unique=False)
    op.create_index("ix_chat_context_checkpoints_user_id", "chat_context_checkpoints", ["user_id"], unique=False)
    op.create_index("ix_chat_context_checkpoints_session_id", "chat_context_checkpoints", ["session_id"], unique=False)


def downgrade() -> None:
    """删除 ChatAgent 会话相关表。"""
    op.drop_index("ix_chat_context_checkpoints_session_id", table_name="chat_context_checkpoints")
    op.drop_index("ix_chat_context_checkpoints_user_id", table_name="chat_context_checkpoints")
    op.drop_index("ix_chat_context_checkpoints_tenant_id", table_name="chat_context_checkpoints")
    op.drop_table("chat_context_checkpoints")

    op.drop_index("ix_chat_messages_status", table_name="chat_messages")
    op.drop_index("ix_chat_messages_session_id", table_name="chat_messages")
    op.drop_index("ix_chat_messages_user_id", table_name="chat_messages")
    op.drop_index("ix_chat_messages_tenant_id", table_name="chat_messages")
    op.drop_table("chat_messages")

    op.drop_index("ix_chat_sessions_parent_session_id", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_status", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_document_id", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_user_id", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_tenant_id", table_name="chat_sessions")
    op.drop_table("chat_sessions")
