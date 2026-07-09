from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from loguru import logger
import os
import uuid

from app.schemas.response.common import ResponseModel, success_response
from app.worker.tasks import analyze_bidding_doc

router = APIRouter()

@router.post("/upload-and-analyze", response_model=ResponseModel[dict])
async def upload_and_analyze(
    file: UploadFile = File(..., description="上传的招标文件 (Word/PDF 等)"),
    company_quals: str = Form(..., description="我方公司的资质信息文本")
):
    """
    上传招标文件，触发后台 AI 提取和对比流程。
    返回 task_id，客户端可通过 SSE 接口订阅进度。
    """
    # 1. 验证前置条件 (Early Return)
    if not file.filename:
        raise HTTPException(status_code=400, detail="未提供有效的文件名")
        
    try:
        # 生成唯一 Task ID
        task_id = str(uuid.uuid4())
        
        # 保存文件到临时目录
        upload_dir = os.path.join(os.getcwd(), "backend", "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        file_path = os.path.join(upload_dir, f"{task_id}_{file.filename}")
        
        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(status_code=400, detail="文件内容为空")
            
        with open(file_path, "wb") as f:
            f.write(file_bytes)
            
        logger.info(f"文件已保存: {file_path}，即将触发 Celery 任务: {task_id}")
        
        # 异步调用 Celery Task
        analyze_bidding_doc.apply_async(
            args=[task_id, file_path, file.filename, company_quals],
            task_id=task_id
        )
        
        # 返回 task_id，前端根据这个 task_id 建立 SSE 连接
        return success_response(data={"task_id": task_id}, message="任务已提交，请通过 SSE 获取进度")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"提交分析任务失败: {str(e)}")
        raise e
