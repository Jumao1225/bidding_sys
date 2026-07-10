import os
import sys
import logging
import argparse
from sqlalchemy.orm import Session

# 将 backend 根目录加入 sys.path，保证可以正常引入 app
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

from app.db.session import SessionLocal
from app.db.models.project import Document, DocChunk
from app.agents.nodes.extractor_agent import extractor_agent_node
from app.agents.state import BiddingState

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_extractor(pdf_path: str):
    if not os.path.exists(pdf_path):
        logger.error(f"测试文件不存在: {pdf_path}")
        return

    db: Session = SessionLocal()
    doc_id = None
    try:
        from app.db.models.project import Project
        
        # 0. 创建一个测试 Project
        logger.info("创建模拟 Project 记录...")
        project = Project(
            tenant_id="test-tenant",
            name="Test Bidding Project",
            status="created"
        )
        db.add(project)
        db.commit()
        db.refresh(project)
        project_id = project.id

        # 1. 模拟在数据库中创建一条 Document 记录
        logger.info("创建模拟 Document 记录...")
        doc = Document(
            tenant_id="test-tenant",
            project_id=project_id,
            filename=os.path.basename(pdf_path),
            file_path=pdf_path,
            parse_status="pending"
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        
        doc_id = doc.id
        logger.info(f"生成测试文档 ID: {doc_id}")

        # 2. 模拟触发 LangGraph 的 Extractor 节点
        state = BiddingState(
            task_id="test-task",
            document_id=doc_id,
            doc_text="",
            company_quals="",
            qualifications_analysis={},
            risks_analysis=[],
            cost_analysis={},
            status="running",
            error=""
        )

        logger.info("=" * 40)
        logger.info("开始调用 Extractor Agent 节点")
        logger.info("=" * 40)
        
        result_state = extractor_agent_node(state)
        
        logger.info(f"Extractor 节点返回状态: {result_state.get('status')}")
        if result_state.get('error'):
            logger.error(f"报错信息: {result_state.get('error')}")
            return

        # 3. 验证数据库插入结果
        chunks = db.query(DocChunk).filter(DocChunk.document_id == doc_id).all()
        logger.info("=" * 40)
        logger.info(f"验证完成！成功从数据库检索到 {len(chunks)} 个切片。")
        logger.info("=" * 40)
        
        if chunks:
            # 打印第一个切片的详情
            first_chunk = chunks[0]
            logger.info(f"【首个切片详情】")
            logger.info(f"页码: {first_chunk.page_num}")
            logger.info(f"章节: {first_chunk.section_title}")
            logger.info(f"类型: {first_chunk.content_type}")
            logger.info(f"内容预览: {first_chunk.content[:200]}...")
            
            # 验证向量维度 (应为 1024)
            # SQLAlchemy 对于 pgvector 会返回 numpy array 或者 list
            vec_dim = len(first_chunk.embedding) if first_chunk.embedding is not None else 0
            logger.info(f"向量维度验证: 预期 1024，实际 {vec_dim}")
            if vec_dim == 1024:
                logger.info("✅ 向量维度完全正确！")
            else:
                logger.error("❌ 向量维度不匹配！")

    except Exception as e:
        logger.exception("测试过程中发生异常")
    finally:
        # 清理生成的测试数据以保持数据库干净
        if doc_id:
            db.query(DocChunk).filter(DocChunk.document_id == doc_id).delete()
            db.query(Document).filter(Document.id == doc_id).delete()
            db.query(Project).filter(Project.id == project_id).delete()
            db.commit()
            logger.info("测试数据清理完毕。")
        db.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extractor Agent 本地测试脚本")
    parser.add_argument("pdf_path", type=str, help="测试 PDF 文件的绝对或相对路径")
    args = parser.parse_args()
    
    test_extractor(args.pdf_path)
