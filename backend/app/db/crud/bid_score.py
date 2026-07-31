"""
标书打分结果数据访问层 (bid_score CRUD)

提供 BidScoreResult 和 BidScoreItem 的增删查操作，
严格遵循租户隔离原则。
"""

from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from loguru import logger

from app.db.models.bid_score import BidScoreResult, BidScoreItem


class BidScoreCRUD:
    """标书打分结果的数据访问对象"""

    # ============================================================
    # BidScoreResult 操作
    # ============================================================

    def create_score_result(
        self,
        db: Session,
        tenant_id: str,
        user_id: str,
        result_data: Dict[str, Any],
    ) -> BidScoreResult:
        """
        创建一条打分会话记录。

        :param db: 数据库会话
        :param tenant_id: 租户 ID
        :param user_id: 用户 ID
        :param result_data: 打分结果数据（不含 tenant_id / user_id）
        :return: 创建的 BidScoreResult 实例
        """
        logger.info(f"📝 [CRUD] 创建打分会话记录, document_id={result_data.get('document_id')}")
        record = BidScoreResult(
            tenant_id=tenant_id,
            user_id=user_id,
            **result_data,
        )
        db.add(record)
        db.flush()  # 获取自动生成的 ID，但不提交（交由上层控制事务）
        logger.info(f"✅ [CRUD] 打分会话记录已创建, result_id={record.id}")
        return record

    def create_score_items_batch(
        self,
        db: Session,
        tenant_id: str,
        user_id: str,
        score_result_id: str,
        items_data: List[Dict[str, Any]],
    ) -> List[BidScoreItem]:
        """
        批量创建逐项打分明细记录。

        :param db: 数据库会话
        :param tenant_id: 租户 ID
        :param user_id: 用户 ID
        :param score_result_id: 关联的打分会话 ID
        :param items_data: 打分明细数据列表
        :return: 创建的 BidScoreItem 实例列表
        """
        logger.info(f"📝 [CRUD] 批量创建打分明细, result_id={score_result_id}, 数量={len(items_data)}")
        records = []
        for item in items_data:
            record = BidScoreItem(
                tenant_id=tenant_id,
                user_id=user_id,
                score_result_id=score_result_id,
                **item,
            )
            records.append(record)

        db.add_all(records)
        db.flush()
        logger.info(f"✅ [CRUD] {len(records)} 条打分明细已批量创建")
        return records

    def get_score_results_by_document(
        self,
        db: Session,
        document_id: str,
        tenant_id: str,
    ) -> List[BidScoreResult]:
        """
        查询指定投标文件的所有历史打分结果（按创建时间倒序）。

        :param db: 数据库会话
        :param document_id: 被评分的投标文件 ID
        :param tenant_id: 租户 ID
        :return: 打分结果列表
        """
        logger.debug(f"🔍 [CRUD] 查询打分历史, document_id={document_id}")
        return (
            db.query(BidScoreResult)
            .filter(
                BidScoreResult.document_id == document_id,
                BidScoreResult.tenant_id == tenant_id,
            )
            .order_by(BidScoreResult.created_at.desc())
            .all()
        )

    def get_latest_score(
        self,
        db: Session,
        document_id: str,
        tenant_id: str,
    ) -> Optional[BidScoreResult]:
        """
        获取指定投标文件的最新一次打分结果。

        :param db: 数据库会话
        :param document_id: 被评分的投标文件 ID
        :param tenant_id: 租户 ID
        :return: 最新的打分结果，无则返回 None
        """
        logger.debug(f"🔍 [CRUD] 查询最新打分, document_id={document_id}")
        return (
            db.query(BidScoreResult)
            .filter(
                BidScoreResult.document_id == document_id,
                BidScoreResult.tenant_id == tenant_id,
            )
            .order_by(BidScoreResult.created_at.desc())
            .first()
        )

    def get_score_result_by_id(
        self,
        db: Session,
        result_id: str,
        tenant_id: str,
    ) -> Optional[BidScoreResult]:
        """
        根据打分会话 ID 查询详情（含逐项明细，通过 selectin 预加载）。

        :param db: 数据库会话
        :param result_id: 打分会话 ID
        :param tenant_id: 租户 ID
        :return: 打分结果实例，无则返回 None
        """
        logger.debug(f"🔍 [CRUD] 查询打分详情, result_id={result_id}")
        return (
            db.query(BidScoreResult)
            .filter(
                BidScoreResult.id == result_id,
                BidScoreResult.tenant_id == tenant_id,
            )
            .first()
        )

    def get_score_items_by_result(
        self,
        db: Session,
        score_result_id: str,
        tenant_id: str,
    ) -> List[BidScoreItem]:
        """
        查询指定打分会话的所有逐项打分明细。

        :param db: 数据库会话
        :param score_result_id: 打分会话 ID
        :param tenant_id: 租户 ID
        :return: 打分明细列表
        """
        logger.debug(f"🔍 [CRUD] 查询打分明细, result_id={score_result_id}")
        return (
            db.query(BidScoreItem)
            .filter(
                BidScoreItem.score_result_id == score_result_id,
                BidScoreItem.tenant_id == tenant_id,
            )
            .all()
        )


# 全局单例
bid_score_crud = BidScoreCRUD()
