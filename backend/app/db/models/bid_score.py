"""
标书打分结果数据模型 (bid_score.py)

定义 BidScoreResult（一次打分会话）和 BidScoreItem（逐项打分明细）两张表，
用于持久化 BidScorerAgent 的打分结果。
"""

from sqlalchemy import String, Text, Float, Integer, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional, List
from .base import TenantBase


class BidScoreResult(TenantBase):
    """
    一次完整的 AI 打分会话结果。
    关联两个文档：被评分的投标文件 (document_id) 和评分维度来源的招标文件 (source_doc_id)。
    """
    __tablename__ = "bid_score_results"

    # 关联的文档 ID
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="被评分的投标文件 Document ID"
    )
    source_doc_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="评分维度来源的招标文件 Document ID"
    )

    # 打分汇总数据
    evaluation_method: Mapped[str | None] = mapped_column(
        String(255), comment="评标方法（如：综合评分法）"
    )
    total_score: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, comment="AI 给出的总分"
    )
    max_possible: Mapped[float] = mapped_column(
        Float, nullable=False, default=100.0, comment="满分值"
    )
    score_rate: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, comment="得分率 (total_score / max_possible)"
    )
    category_scores: Mapped[dict | None] = mapped_column(
        JSON, comment="按大类聚合的分数 JSON"
    )

    # 总评与建议
    summary: Mapped[str | None] = mapped_column(
        Text, comment="LLM 生成的总体评价摘要"
    )
    top_improvements: Mapped[list | None] = mapped_column(
        JSON, comment="优先级排序的改进建议列表"
    )
    validation_warnings: Mapped[list | None] = mapped_column(
        JSON, comment="数学校验告警列表"
    )

    # 打分配置与元信息
    scoring_rounds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, comment="共识轮数（默认 3）"
    )
    model_name: Mapped[str | None] = mapped_column(
        String(255), comment="使用的 LLM 模型名称"
    )

    # 关联的逐项打分明细
    score_items: Mapped[List["BidScoreItem"]] = relationship(
        "BidScoreItem", back_populates="score_result",
        cascade="all, delete-orphan", lazy="selectin"
    )


class BidScoreItem(TenantBase):
    """
    逐项打分明细。每个实例对应 score_tree 中一个 ScoreDetail 的打分结果。
    通过三轮共识投票产生最终分数。
    """
    __tablename__ = "bid_score_items"

    # 关联打分会话
    score_result_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("bid_score_results.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="关联的打分会话 ID"
    )

    # 评分项标识
    item_code: Mapped[str | None] = mapped_column(
        String(100), comment="评分项编号（如 '1.1'、'技术三'）"
    )
    category: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="一级分类（如：技术分/商务分/价格分）"
    )
    sub_category: Mapped[str | None] = mapped_column(
        String(100), comment="二级分类（如：施工方案/团队配置）"
    )
    title: Mapped[str] = mapped_column(
        String(500), nullable=False, comment="评分项名称"
    )

    # 打分结果
    max_score: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, comment="该项满分"
    )
    ai_score: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, comment="AI 打分（三轮中位数）"
    )
    confidence: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, comment="置信度（三轮一致性 0.0~1.0）"
    )
    score_variance: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, comment="三轮分数标准差"
    )
    all_round_scores: Mapped[list | None] = mapped_column(
        JSON, comment="三轮原始分数 [round1, round2, round3]"
    )

    # 评分依据与建议
    scoring_basis: Mapped[str | None] = mapped_column(
        Text, comment="评分依据（引用投标文件原文）"
    )
    deduction_reason: Mapped[str | None] = mapped_column(
        Text, comment="扣分原因"
    )
    suggestion: Mapped[str | None] = mapped_column(
        Text, comment="该项的改进建议"
    )

    # 关联打分会话
    score_result: Mapped["BidScoreResult"] = relationship(
        "BidScoreResult", back_populates="score_items"
    )
