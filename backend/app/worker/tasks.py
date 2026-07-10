import redis
import json
import os
from loguru import logger
from app.core.celery_app import celery_app
from app.core.config import settings
from app.utils.doc_parser import DocumentParser
from app.graph.builder import bidding_graph

# 初始化 redis 客户端用于 pub/sub
redis_client = redis.from_url(settings.REDIS_URL)

def publish_progress(task_id: str, status: str, progress: int, result: dict = None):
    """
    推送进度信息到 Redis Pub/Sub 供 SSE 读取
    """
    message = {
        "status": status,
        "progress": progress,
    }
    if result is not None:
        message["result"] = result
        
    redis_client.publish(f"channel:{task_id}", json.dumps(message))

@celery_app.task(bind=True, name="analyze_bidding_doc")
def analyze_bidding_doc(self, task_id: str, file_path: str, filename: str, company_quals: str):
    """
    后台处理招标文件解析和 AI 分析
    """
    logger.info(f"Task {task_id} started for file {filename}")
    publish_progress(task_id, "开始处理", 10)
    
    from app.db.session import SessionLocal
    from app.db.models.project import Project, Document
    
    db = SessionLocal()
    doc_id = None
    try:
        # 1. 创建默认 Project (如果需要) 并插入 Document 记录供 Extractor 使用
        publish_progress(task_id, "初始化任务与数据库...", 15)
        
        project = db.query(Project).filter(Project.name == "Frontend Uploads").first()
        if not project:
            project = Project(tenant_id="default-tenant", name="Frontend Uploads", status="created")
            db.add(project)
            db.commit()
            db.refresh(project)
            
        doc = Document(
            tenant_id="default-tenant",
            project_id=project.id,
            filename=filename,
            file_path=file_path,
            parse_status="pending"
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        doc_id = doc.id
        
        publish_progress(task_id, "正在提取文本与生成向量 (Docling + BGE-M3)...", 20)
        
        # 2. 调用 LangGraph
        initial_state = {
            "task_id": task_id,
            "document_id": doc_id,
            "doc_text": "",
            "company_quals": company_quals,
            "status": "RUNNING",
            "error": ""
        }
        
        # graph.invoke 会返回最终状态
        final_state = bidding_graph.invoke(initial_state)
        
        # 提取结果用于前端展示
        result = {
            "extracted_text": final_state.get("doc_text", ""),
            "qualifications_analysis": final_state.get("qualifications_analysis", {}),
            "risks_analysis": final_state.get("risks_analysis", []),
            "cost_analysis": final_state.get("cost_analysis", {})
        }
        
        if final_state.get("status") == "extractor_failed" or final_state.get("error"):
            raise Exception(final_state.get("error", "智能体执行失败"))
            
        publish_progress(task_id, "完成", 100, result=result)
        logger.info(f"Task {task_id} completed.")
        return final_state
        
    except Exception as e:
        logger.exception(f"Task {task_id} failed: {e}")
        publish_progress(task_id, f"错误: {str(e)}", 100, result={"error": str(e)})
        raise e
    finally:
        db.close()
        # 清理临时文件 - 暂时禁用，前端需要读取原文件预览
        # if os.path.exists(file_path):
        #     os.remove(file_path)
        pass
