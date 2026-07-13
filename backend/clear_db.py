import sys
import os
import logging

sys.path.insert(0, os.path.abspath('.'))

from sqlalchemy.orm import Session
from sqlalchemy import text
from app.db.session import SessionLocal
from app.db.models.project import Project, Document, DocChunk

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

db: Session = SessionLocal()
try:
    # 由于有外键级联删除 (CASCADE)，直接删除所有的 Project 即可
    # 但为了保险起见，我们逐级清空
    logger.info("开始清空 doc_chunks 表...")
    db.query(DocChunk).delete()
    
    logger.info("开始清空 documents 表...")
    db.query(Document).delete()
    
    logger.info("开始清空 projects 表...")
    db.query(Project).delete()
    
    db.commit()
    logger.info("✅ 数据库内容已全部清空！您现在可以从头开始上传和解析文档了。")
except Exception as e:
    db.rollback()
    logger.error(f"清空数据库失败: {e}")
finally:
    db.close()
