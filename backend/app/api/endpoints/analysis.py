from fastapi import APIRouter, UploadFile, File, Form, HTTPException, BackgroundTasks, Depends
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from loguru import logger
import os
import uuid
from pathlib import Path
import glob

from app.schemas.response.common import ResponseModel, success_response
from app.worker.tasks import analyze_bidding_doc
from app.agents.tools.metadata_tools import (
    extract_qualification_info,
    extract_financial_info,
    extract_timeline_info,
    extract_engineering_info,
    extract_evaluation_info
)

router = APIRouter()

from app.db.models.user import User
from app.api import deps

@router.post("/upload-and-analyze", response_model=ResponseModel[dict])
async def upload_and_analyze(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="上传的招标文件 (Word/PDF 等)"),
    company_quals: str = Form(..., description="我方公司的资质信息文本"),
    current_user: User = Depends(deps.get_current_active_user)
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
        base_dir = Path(__file__).resolve().parent.parent.parent.parent
        upload_dir = os.path.join(base_dir, "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        file_path = os.path.join(upload_dir, f"{task_id}_{file.filename}")
        
        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(status_code=400, detail="文件内容为空")
            
        with open(file_path, "wb") as f:
            f.write(file_bytes)
            
        logger.info(f"文件已保存: {file_path}，即将触发 Celery 任务: {task_id}")
        
        # 触发后台异步任务
        background_tasks.add_task(
            analyze_bidding_doc,
            task_id, 
            file_path, 
            file.filename, 
            company_quals,
            current_user.id,
            current_user.tenant_id
        )
        
        # 返回 task_id，前端根据这个 task_id 建立 SSE 连接
        return success_response(data={"task_id": task_id}, message="任务已提交，请通过 SSE 获取进度")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"提交分析任务失败: {str(e)}")
        raise e

def get_db():
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/{document_id}/reextract/{domain}", response_model=ResponseModel[dict])
async def reextract_domain(
    document_id: str, 
    domain: str, 
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_user)
):
    """
    针对特定的元数据领域（domain）进行重新提取，并返回最新结果。
    """
    domain_map = {
        "qualification": extract_qualification_info,
        "financial": extract_financial_info,
        "timeline": extract_timeline_info,
        "engineering": extract_engineering_info,
        "evaluation": extract_evaluation_info
    }
    
    if domain not in domain_map and domain not in ("cost_estimation", "cost"):
        raise HTTPException(status_code=400, detail=f"未知的提取领域: {domain}")
        
    try:
        from app.db.crud.document import document_crud
        from app.worker.tasks import emit_agent_log
        from app.core.context import current_task_id, current_user_id, current_tenant_id
        
        # 鉴权验证：确保文档属于当前用户
        doc = document_crud.get_document_by_id(db, document_id, current_user.id, current_user.tenant_id)
        if not doc:
            raise HTTPException(status_code=403, detail="无权访问该文档或文档不存在")
            
        # 为了让 emit_agent_log 生效，并满足安全鉴权，注入全链路上下文
        token_task = current_task_id.set(document_id)
        token_user = current_user_id.set(current_user.id)
        token_tenant = current_tenant_id.set(current_user.tenant_id)
        
        try:
            if domain in ("cost_estimation", "cost"):
                from sqlalchemy.orm.attributes import flag_modified
                from app.agents.nodes.cost_agent import cost_node
                
                state = {
                    "document_id": document_id,
                    "user_id": current_user.id,
                    "tenant_id": current_user.tenant_id
                }
                cost_result = cost_node(state)
                cost_data = cost_result.get("cost_analysis", {})
                
                # 持久化更新至数据库 parsed_metadata
                parsed_metadata = dict(doc.parsed_metadata or {})
                parsed_metadata["cost_analysis"] = cost_data
                doc.parsed_metadata = parsed_metadata
                flag_modified(doc, "parsed_metadata")
                db.commit()
                
                return success_response(data=cost_data, message="成本测算重新计算成功")
            
            tool_func = domain_map[domain]
            # 调用工具提取（其内部已包含落盘逻辑）
            res_str = tool_func.invoke({"document_id": document_id})
            
            import json
            if res_str and res_str.startswith("{"):
                res_data = json.loads(res_str)
                if "error" in res_data:
                    logger.error(f"重新提取 {domain} 失败: {res_data['error']}")
                    raise HTTPException(status_code=500, detail=f"重新提取失败: {res_data['error']}")
                return success_response(data=res_data, message=f"{domain} 领域重新提取成功")
            else:
                logger.error(f"重新提取 {domain} 失败或无权限: {res_str}")
                raise HTTPException(status_code=500, detail=f"重新提取失败: {res_str}")
        finally:
            current_task_id.reset(token_task)
            current_user_id.reset(token_user)
            current_tenant_id.reset(token_tenant)
            
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"重新提取 {domain} 异常: {str(e)}")
        raise HTTPException(status_code=500, detail=f"重新提取异常: {str(e)}")

@router.api_route("/download/{task_id}", methods=["GET", "HEAD"])
async def download_original_file(
    task_id: str, 
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_active_user)
):
    """
    根据 task_id 或 document_id 下载原文件
    """
    base_dir = Path(__file__).resolve().parent.parent.parent.parent
    upload_dir = os.path.join(base_dir, "uploads")
    
    # 1. 首先尝试按照 document_id 查找 (用于历史记录)并验证权限
    from app.db.crud.document import document_crud
    doc = document_crud.get_document_by_id(db, task_id, current_user.id, current_user.tenant_id)
    if doc and doc.file_path and os.path.exists(doc.file_path):
        return FileResponse(
            path=doc.file_path, 
            filename=doc.filename,
            content_disposition_type="inline"
        )
    
    # 查找匹配 task_id 的文件
    pattern = os.path.join(upload_dir, f"{task_id}_*")
    matched_files = glob.glob(pattern)
    if not matched_files:
        raise HTTPException(status_code=404, detail="未找到对应的原文件")
    
    file_path = matched_files[0]
    filename = os.path.basename(file_path).replace(f"{task_id}_", "")
    
    return FileResponse(
        path=file_path, 
        filename=filename,
        # Content-Disposition "inline" allows browser to try displaying it (good for PDF)
        content_disposition_type="inline"
    )
