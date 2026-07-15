from sqlalchemy import String, Text, ForeignKey, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import List, Optional
from pgvector.sqlalchemy import Vector
from .base import TenantBase

class Project(TenantBase):
    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="created")

    documents: Mapped[List["Document"]] = relationship("Document", back_populates="project", cascade="all, delete-orphan")

class Document(TenantBase):
    __tablename__ = "documents"

    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    parse_status: Mapped[str] = mapped_column(String(50), default="pending")
    parsed_metadata: Mapped[dict | None] = mapped_column(JSON)

    project: Mapped["Project"] = relationship("Project", back_populates="documents")
    chunks: Mapped[List["DocChunk"]] = relationship("DocChunk", back_populates="document", cascade="all, delete-orphan")

class DocChunk(TenantBase):
    __tablename__ = "doc_chunks"

    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0, comment="文档内切片顺序索引, 从0开始递增")
    page_num: Mapped[int | None] = mapped_column(Integer)
    section_title: Mapped[str | None] = mapped_column(String(255))
    content_type: Mapped[str | None] = mapped_column(String(50))
    trace_info: Mapped[dict | None] = mapped_column(JSON)
    embedding: Mapped[list[float]] = mapped_column(Vector(1024))
    
    document: Mapped["Document"] = relationship("Document", back_populates="chunks")
