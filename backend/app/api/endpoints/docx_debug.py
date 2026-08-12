"""
DocxDebug Router - Word 格式与 DOM 修改调试 API 端点

功能说明：
1. 提供 /api/v1/docx/debug-modify 接口：
   - 接收上传的 .docx 物理文件与自然语言修改指令；
   - 结合智能规则解析修改指令，应用 docx 技能规范（下划线保持、DXA 双宽度设置、纯黑字体）；
   - 返回修改后的 Word 二进制文件流并提供修改日志；
2. 提供 /api/v1/docx/generate-sample 接口：
   - 动态生成标准标书测试模版 .docx 供调试测试。
"""

import io
import json
import re
from typing import Dict, Any, Optional
from loguru import logger
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

from app.services.docx_test_filler_service import docx_test_filler_service
from app.services.docx_skill_service import docx_skill_service
from app.services.llm_service import llm_service

router = APIRouter()


def _parse_prompt_to_fill_data(prompt: str) -> Dict[str, str]:
    """
    解析用户输入的自由自然语言修改指令，提炼为 键-值 规则字典
    例："将项目名称改为智能AI系统，把投标人名称修改为聚猫科技，报价改为500000"
    -> {"项目名称": "智能AI系统", "投标人名称": "聚猫科技", "报价": "500000"}
    """
    fill_data: Dict[str, str] = {}
    if not prompt:
        return fill_data

    # 优先尝试 JSON 格式解析
    try:
        if prompt.strip().startswith('{') and prompt.strip().endswith('}'):
            parsed = json.loads(prompt)
            if isinstance(parsed, dict):
                return {str(k): str(v) for k, v in parsed.items()}
    except Exception:
        pass

    # 正则与关键词提取逻辑（使用 (?:...) 规范分组，避免 | 运算符优先级混乱）
    patterns = [
        (r'(?:项目名称)[改设为是：:\s]+([^\s,，;；\n]+)', "项目名称"),
        (r'(?:项目编号)[改设为是：:\s]+([^\s,，;；\n]+)', "项目编号"),
        (r'(?:投标人名称|投标人全称|投标人)[改设为是：:\s]+([^\s,，;；\n]+)', "投标人名称"),
        (r'(?:法定代表人|法人代表)[改设为是：:\s]+([^\s,，;；\n]+)', "法定代表人"),
        (r'(?:授权代理人|委托代理人)[改设为是：:\s]+([^\s,，;；\n]+)', "授权代理人"),
        (r'(?:工期|服务期限)[改设为是：:\s]+([^\s,，;；\n]+)', "工期"),
        (r'(?:投标总报价|投标总价|投标报价|总报价|报价)[改设为是：:\s]+([0-9.,万亿元整]+|[^\s,，;；\n]+)', "投标总价"),
        (r'(?:投标日期|日期|时间)[改设为是：:\s]+([^\s,，;；\n]+)', "投标日期"),
    ]

    for pattern, key in patterns:
        match = re.search(pattern, prompt)
        if match and match.group(1):
            val = match.group(1).strip()
            # 过滤掉多余的引导尾缀（如："，填入对应数据" -> "967840.36"）
            val = re.sub(r'[,，;；\s].*', '', val)
            if val:
                fill_data[key] = val

    # 通用 键=值 或 键：值 解析
    kv_matches = re.findall(r'([\u4e00-\u9fa5a-zA-Z0-9_]+)\s*[:：=]\s*([^\s,，;；\n]+)', prompt)
    for k, v in kv_matches:
        if k not in fill_data and v:
            fill_data[k] = v.strip()

    # 如果正则未能成功抓取任何有效键值对，且输入包含纯数字金额
    if "投标总价" not in fill_data:
        num_match = re.search(r'(?:金额|报价|总价|价格)[^\d]*([0-9]+(?:\.[0-9]+)?)', prompt)
        if num_match:
            fill_data["投标总价"] = num_match.group(1)

    # 后备兜底
    if not fill_data and prompt.strip():
        fill_data["项目名称"] = prompt.strip()

    return fill_data


@router.post("/debug-modify", summary="上传 Word 文件并按指令修改")
async def debug_modify_docx(
    file: UploadFile = File(...),
    prompt: str = Form(...)
):
    """
    调试端点：接收 Word (.docx) 文件与修改指令，应用 docx 技能进行原位替换并返回二进制文档。
    """
    if not file.filename or not file.filename.lower().endswith('.docx'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="只支持上传 .docx 格式的 Word 文档"
        )

    try:
        docx_bytes = await file.read()
        if not docx_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="上传的文件内容为空"
            )

        logger.info(f"收到 Word 调试修改请求，文件名: {file.filename}, 指令: {prompt}")

        # 1. 解析指令为结构化键值
        fill_data = _parse_prompt_to_fill_data(prompt)
        logger.info(f"指令解析结果字典: {fill_data}")

        # 2. 构造默认表格更新规则（若有报价或项目数据）
        table_updates = None
        if "投标总价" in fill_data or "报价" in fill_data:
            price_val = fill_data.get("投标总价") or fill_data.get("报价")
            table_updates = {
                "row_1": ["1", fill_data.get("项目名称", "智能填报响应模块"), price_val]
            }

        # 3. 调用基于 docx 技能的修改服务（线程池异步化）
        modified_bytes = await run_in_threadpool(
            docx_test_filler_service.fill_and_modify_docx,
            docx_bytes=docx_bytes,
            fill_data=fill_data,
            table_updates=table_updates
        )

        from urllib.parse import quote

        filename_encode = quote(f"modified_{file.filename}")
        keys_encode = quote(json.dumps(list(fill_data.keys()), ensure_ascii=False))

        return Response(
            content=modified_bytes,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "Content-Disposition": f"attachment; filename*=utf-8''{filename_encode}",
                "X-Modified-Keys": keys_encode
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("处理 Word 调试修改失败")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"修改 Word 文档失败: {str(e)}"
        )


@router.get("/generate-sample", summary="一键生成测试模版 Word")
async def generate_sample_docx():
    """
    一键生成标准标书 Word 测试模版，供无本地文件时快速体验调试。
    """
    try:
        sample_bytes = docx_test_filler_service.create_sample_docx()
        return Response(
            content=sample_bytes,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "Content-Disposition": "attachment; filename=bidding_test_template.docx"
            }
        )
    except Exception as e:
        logger.exception("生成测试模版 Word 失败")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"生成测试模版失败: {str(e)}"
        )


@router.post("/accept-tracked-changes", summary="接受 Word 文档中的全部修订痕迹")
async def accept_tracked_changes_api(file: UploadFile = File(...)):
    """
    接收上传的 Word (.docx)，全量接受其中的修订痕迹，返回干净正文文件。
    """
    if not file.filename or not file.filename.lower().endswith('.docx'):
        raise HTTPException(status_code=400, detail="只支持上传 .docx 格式文件")

    try:
        docx_bytes = await file.read()
        res_bytes = await run_in_threadpool(docx_skill_service.accept_tracked_changes, docx_bytes)
        from urllib.parse import quote
        filename_encode = quote(f"accepted_{file.filename}")
        return Response(
            content=res_bytes,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f"attachment; filename*=utf-8''{filename_encode}"}
        )
    except Exception as e:
        logger.exception("接受修订痕迹失败")
        raise HTTPException(status_code=500, detail=f"接受修订痕迹失败: {str(e)}")


@router.post("/insert-toc", summary="为 Word 文档自动插入/更新目录")
async def insert_toc_api(file: UploadFile = File(...)):
    """
    接收上传的 Word (.docx)，在占位符或头部自动添加 Word 动态目录。
    """
    if not file.filename or not file.filename.lower().endswith('.docx'):
        raise HTTPException(status_code=400, detail="只支持上传 .docx 格式文件")

    try:
        docx_bytes = await file.read()
        res_bytes = await run_in_threadpool(docx_skill_service.insert_table_of_contents, docx_bytes)
        from urllib.parse import quote
        filename_encode = quote(f"toc_{file.filename}")
        return Response(
            content=res_bytes,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f"attachment; filename*=utf-8''{filename_encode}"}
        )
    except Exception as e:
        logger.exception("插入目录失败")
        raise HTTPException(status_code=500, detail=f"插入目录失败: {str(e)}")


@router.post("/scrub-privacy", summary="为 Word 文档进行隐私与元数据脱敏清洗")
async def scrub_privacy_api(file: UploadFile = File(...)):
    """
    接收上传的 Word (.docx)，抹去作者姓名、修改记录及痕迹 ID 等隐秘数据。
    """
    if not file.filename or not file.filename.lower().endswith('.docx'):
        raise HTTPException(status_code=400, detail="只支持上传 .docx 格式文件")

    try:
        docx_bytes = await file.read()
        res_bytes = await run_in_threadpool(docx_skill_service.scrub_privacy_metadata, docx_bytes)
        from urllib.parse import quote
        filename_encode = quote(f"scrubbed_{file.filename}")
        return Response(
            content=res_bytes,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f"attachment; filename*=utf-8''{filename_encode}"}
        )
    except Exception as e:
        logger.exception("隐私清洗失败")
        raise HTTPException(status_code=500, detail=f"隐私清洗失败: {str(e)}")


@router.post("/extract-comments", summary="提取 Word 文档中的全部审阅批注")
async def extract_comments_api(file: UploadFile = File(...)):
    """
    接收上传的 Word (.docx)，抓取并返回所有的批注列表。
    """
    if not file.filename or not file.filename.lower().endswith('.docx'):
        raise HTTPException(status_code=400, detail="只支持上传 .docx 格式文件")

    try:
        docx_bytes = await file.read()
        comments = await run_in_threadpool(docx_skill_service.extract_comments, docx_bytes)
        return {"code": 200, "message": "成功提取批注", "data": comments}
    except Exception as e:
        logger.exception("提取批注失败")
        raise HTTPException(status_code=500, detail=f"提取批注失败: {str(e)}")


@router.post("/strip-comments", summary="一键删除 Word 文档中的全部批注")
async def strip_comments_api(file: UploadFile = File(...)):
    """
    接收上传的 Word (.docx)，彻底剔除其中的审阅批注节点，返回无批注的干净 Word 文件。
    """
    if not file.filename or not file.filename.lower().endswith('.docx'):
        raise HTTPException(status_code=400, detail="只支持上传 .docx 格式文件")

    try:
        docx_bytes = await file.read()
        res_bytes = await run_in_threadpool(docx_skill_service.strip_comments, docx_bytes)
        from urllib.parse import quote
        filename_encode = quote(f"no_comments_{file.filename}")
        return Response(
            content=res_bytes,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f"attachment; filename*=utf-8''{filename_encode}"}
        )
    except Exception as e:
        logger.exception("剔除 Word 批注失败")
        raise HTTPException(status_code=500, detail=f"剔除 Word 批注失败: {str(e)}")


