import os
import uuid
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import PlainTextResponse
from loguru import logger

from app.schemas.response.common import ResponseModel, success_response
from app.schemas.response.mineru import MinerUParseResponse, MinerUHealthResponse
from app.services.mineru_service import MinerUService

router = APIRouter()
mineru_service = MinerUService()


@router.get("/status", response_model=ResponseModel[MinerUHealthResponse])
async def get_mineru_status():
    """
    查询服务器上 MinerU (magic-pdf) 环境可用性与配置诊断状态
    """
    try:
        status_info = mineru_service.check_availability()
        response_data = MinerUHealthResponse(**status_info)
        return success_response(data=response_data, message="成功获取 MinerU 服务状态")
    except Exception as e:
        logger.exception(f"获取 MinerU 状态失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"检查环境失败: {str(e)}")


@router.post("/parse", response_model=ResponseModel[MinerUParseResponse])
async def parse_document(
    file: UploadFile = File(..., description="要测试解析的文档 (PDF/Word 等)"),
    parse_mode: str = Form("auto", description="解析模式: auto (自动识别), txt (纯文本), ocr (强制OCR)")
):
    """
    测试文件解析接口：
    上传文档后由 MinerU / 兼容组件处理，并落盘 Markdown 文件供在线预览和提取结构化章节。
    """
    # 1. 拦截防御与尽早返回 (Early Return)
    if not file.filename:
        raise HTTPException(status_code=400, detail="必须上传有效的文件")

    task_id = str(uuid.uuid4())
    
    # 2. 保存文件到临时上传目录
    base_dir = Path(__file__).resolve().parent.parent.parent.parent
    upload_dir = base_dir / "uploads" / "temp_mineru"
    os.makedirs(upload_dir, exist_ok=True)

    file_path = upload_dir / f"{task_id}_{file.filename}"

    try:
        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(status_code=400, detail="上传的文件内容不能为空")

        with open(file_path, "wb") as f:
            f.write(file_bytes)

        logger.info(f"上传文件已暂存: {file_path}，开始提交 MinerUService 解析...")

        # 3. 调用 Service 执行解析
        result = mineru_service.parse_file(
            file_path=str(file_path),
            task_id=task_id,
            parse_mode=parse_mode
        )

        response_data = MinerUParseResponse(**result)
        return success_response(data=response_data, message="文件解析完成")

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"MinerU 文件解析接口发生异常: {str(e)}")
        raise HTTPException(status_code=500, detail=f"文件解析失败: {str(e)}")
    finally:
        # 清理临时上传的源文件
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass


@router.get("/preview-md/{task_id}", response_class=PlainTextResponse)
async def preview_markdown_file(task_id: str):
    """
    直接查看/阅读特定任务解析导出的原始 Markdown 文本文件
    """
    md_path = mineru_service.output_base_dir / task_id / "output.md"
    
    if not os.path.exists(md_path):
        raise HTTPException(status_code=404, detail=f"未找到任务 [{task_id}] 对应的 Markdown 文件")

    try:
        with open(md_path, "r", encoding="utf-8") as f:
            content = f.read()
        return PlainTextResponse(content=content, media_type="text/markdown")
    except Exception as e:
        logger.exception(f"读取 Markdown 文件失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"读取文件错误: {str(e)}")
