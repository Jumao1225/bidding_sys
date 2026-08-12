"""
存量文档物理路径与元信息迁移脚本 (migrate_document_paths.py)

功能：
1. 自动在 backend/uploads/ 下创建 tenders/ 与 bids/ 物理目录；
2. 扫描数据库 Document 表中的所有记录；
3. 将根目录 backend/uploads/ 下的物理文件分别安全搬迁至 tenders/ 或 bids/ 子目录；
4. 同步更新数据库中 Document.file_path 与 Document.parsed_metadata 中的 doc_type 元数据。
"""

import os
import shutil
import sys
from pathlib import Path

# 将 backend 根目录加入 sys.path 以便导入 app 模块
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from loguru import logger
from app.db.session import SessionLocal
from app.db.models.project import Document

def migrate_documents():
    """执行物理文件与数据库记录同步迁移"""
    uploads_dir = backend_dir / "uploads"
    tenders_dir = uploads_dir / "tenders"
    bids_dir = uploads_dir / "bids"

    tenders_dir.mkdir(parents=True, exist_ok=True)
    bids_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"📂 [Migration] 物理目录检查完毕:")
    logger.info(f"   - 招标文件库: {tenders_dir}")
    logger.info(f"   - 投标文件库: {bids_dir}")

    db = SessionLocal()
    try:
        docs = db.query(Document).all()
        logger.info(f"🔍 [Migration] 共找到 {len(docs)} 条 Document 数据库记录，开始执行平滑迁移...")

        migrated_count = 0
        updated_meta_count = 0

        for doc in docs:
            pm = dict(doc.parsed_metadata or {})
            existing_type = pm.get("doc_type")
            
            # 判断文档类型: 若显式标注为 bid 或在 temp_uploads/bid_docs 目录下，归为 bid；否则归为 tender
            current_path_str = str(doc.file_path or "").replace("\\", "/")
            is_bid = (
                existing_type == "bid" 
                or "/bids/" in current_path_str 
                or "temp_uploads" in current_path_str 
                or "bid_docs" in current_path_str
            )
            
            target_doc_type = "bid" if is_bid else "tender"
            target_dir = bids_dir if is_bid else tenders_dir

            # 标记 doc_type
            pm["doc_type"] = target_doc_type
            doc.parsed_metadata = pm
            updated_meta_count += 1

            # 检查物理路径迁移
            if doc.file_path and os.path.exists(doc.file_path):
                old_file_path = Path(doc.file_path).resolve()
                # 如果已经位于目标子目录中，则无需移动文件
                if target_dir.resolve() in old_file_path.parents:
                    continue

                filename = old_file_path.name
                new_file_path = target_dir / filename

                # 处理重名
                if new_file_path.exists() and new_file_path.resolve() != old_file_path.resolve():
                    new_file_path = target_dir / f"migrated_{doc.id[:8]}_{filename}"

                try:
                    shutil.move(str(old_file_path), str(new_file_path))
                    doc.file_path = str(new_file_path)
                    migrated_count += 1
                    logger.info(f"🚚 物理文件移动成功: {old_file_path.name} -> {target_doc_type}/{new_file_path.name}")
                except Exception as e:
                    logger.error(f"❌ 移动物理文件失败 {old_file_path}: {e}")

        db.commit()
        logger.info(f"✅ [Migration] 迁移全流程完成！共更新 {updated_meta_count} 条数据库元数据，物理搬迁 {migrated_count} 个文件。")

    except Exception as e:
        db.rollback()
        logger.exception(f"❌ [Migration] 迁移过程发生异常: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    migrate_documents()
