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
    
    try:
        # 1. 解析文档
        publish_progress(task_id, "提取文本", 20)
        with open(file_path, "rb") as f:
            file_bytes = f.read()
            
        extracted_text = DocumentParser.extract_text_from_word(
            file_bytes=file_bytes, 
            filename=filename
        )
        
        if not extracted_text:
            raise Exception("未能提取到有效文本")
            
        publish_progress(task_id, "正在进行资质评估...", 40)
        
        # 2. 调用 LangGraph
        initial_state = {
            "task_id": task_id,
            "doc_text": extracted_text,
            "company_quals": company_quals,
            "status": "RUNNING",
            "error": ""
        }
        
        # 遍历图的执行，获取中间状态可以用于进度推送，但为简化直接 invoke
        # graph.invoke 会返回最终状态
        final_state = bidding_graph.invoke(initial_state)
        
        publish_progress(task_id, "完成", 100, result=final_state)
        logger.info(f"Task {task_id} completed.")
        return final_state
        
    except Exception as e:
        logger.exception(f"Task {task_id} failed: {e}")
        publish_progress(task_id, f"错误: {str(e)}", 100, result={"error": str(e)})
        raise e
    finally:
        # 清理临时文件
        if os.path.exists(file_path):
            os.remove(file_path)
