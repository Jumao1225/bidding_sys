"""分析专项结果的增量持久化服务。"""

from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from loguru import logger
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.db.models.project import Document


ANALYSIS_STATUS_KEY = "analysis_status"


def persist_worker_analysis_result(
    document_id: Optional[str],
    tenant_id: Optional[str],
    user_id: Optional[str],
    worker_name: str,
    result_updates: Optional[Mapping[str, Any]] = None,
    status: str = "completed",
    attempts: int = 1,
    error_type: Optional[str] = None,
) -> bool:
    """合并保存单个 Worker 结果，并记录该 Worker 的最终状态。

    使用数据库行锁保证并发 Worker 读取到最新的 JSON 快照，避免后写入的结果覆盖先写入的结果。
    """

    if not document_id:
        logger.warning("跳过分析结果持久化：缺少 document_id，worker={}", worker_name)
        return False

    from app.db.session import SessionLocal

    db: Session = SessionLocal()
    try:
        query = db.query(Document).filter(Document.id == document_id)
        if tenant_id:
            query = query.filter(Document.tenant_id == tenant_id)
        if user_id:
            query = query.filter(Document.user_id == user_id)

        # 并发 Worker 必须在锁内重新读取 parsed_metadata，不能使用调用方缓存的旧对象。
        document = query.with_for_update().first()
        if not document:
            raise ValueError(f"未找到可写入分析结果的文档: {document_id}")

        parsed_metadata = dict(document.parsed_metadata or {})
        for key, value in (result_updates or {}).items():
            parsed_metadata[key] = value

        status_map = parsed_metadata.get(ANALYSIS_STATUS_KEY)
        if not isinstance(status_map, dict):
            status_map = {}

        worker_status: dict[str, Any] = {
            "status": status,
            "attempts": max(1, int(attempts)),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if error_type:
            worker_status["error_type"] = error_type
        status_map[worker_name] = worker_status
        parsed_metadata[ANALYSIS_STATUS_KEY] = status_map

        document.parsed_metadata = parsed_metadata
        flag_modified(document, "parsed_metadata")
        db.commit()
        logger.info(
            "分析专项结果已增量保存: document_id={}, worker={}, status={}, attempts={}",
            document_id,
            worker_name,
            status,
            worker_status["attempts"],
        )
        return True
    except Exception:
        db.rollback()
        logger.exception(
            "分析专项结果增量保存失败: document_id={}, worker={}",
            document_id,
            worker_name,
        )
        raise
    finally:
        db.close()
