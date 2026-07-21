import os
import io
import time
import uuid
import zipfile
import requests
from pathlib import Path
from typing import Dict, Any, Optional
from loguru import logger

from app.core.config import settings
from app.services.parsers.base_parser import BaseParser

class MinerUParser(BaseParser):
    """
    MinerU 官方 HTTP API 智能文档解析器。
    用于处理 PDF 等高度依赖 OCR 与多模态抽取的复杂文档。
    """
    def __init__(self, output_base_dir: Optional[str] = None):
        if output_base_dir:
            self.output_base_dir = Path(output_base_dir)
        else:
            base_dir = Path(__file__).resolve().parent.parent.parent.parent
            self.output_base_dir = base_dir / "uploads" / "mineru_output"

        os.makedirs(self.output_base_dir, exist_ok=True)
        self.api_token = settings.MINERU_API_TOKEN
        self.api_base_url = settings.MINERU_API_BASE_URL.rstrip("/")

    def check_availability(self) -> Dict[str, Any]:
        has_token = bool(self.api_token and self.api_token.strip())
        if has_token:
            return {
                "is_installed": True,
                "has_api_token": True,
                "executable_path": "MinerU-Online-HTTP-API",
                "supported_formats": ["pdf", "docx", "doc", "ppt", "pptx", "xls", "xlsx", "png", "jpg", "html"],
                "message": "MinerU 官方在线 HTTP API 服务准备就绪（已配置 MINERU_API_TOKEN）。"
            }
        return {
            "is_installed": False,
            "has_api_token": False,
            "executable_path": None,
            "supported_formats": ["docx", "doc"],
            "message": "未配置 MINERU_API_TOKEN，MinerU 解析引擎不可用。"
        }

    def _parse_via_cloud_api(
        self,
        file_path: str,
        task_id: str,
        model_version: str = "vlm",
        max_poll_seconds: int = 120
    ) -> Optional[str]:
        if not self.api_token:
            logger.warning("未配置 MINERU_API_TOKEN，无法发起云端 HTTP 接口调用。")
            return None

        file_name = os.path.basename(file_path)
        ext = os.path.splitext(file_name)[1].lower() or ".pdf"
        sanitized_name = f"doc_{task_id[:8].replace('-', '')}{ext}"
        
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json"
        }

        try:
            apply_url = f"{self.api_base_url}/file-urls/batch"
            apply_payload = {
                "files": [{"name": sanitized_name, "data_id": task_id}],
                "model_version": model_version
            }
            logger.info(f"正在向 MinerU 云端 API 申请上传凭证 ({sanitized_name})")
            res = requests.post(apply_url, headers=headers, json=apply_payload, timeout=30, proxies={"http": None, "https": None})
            res.raise_for_status()
            res_data = res.json()

            if res_data.get("code") != 0:
                logger.error(f"MinerU 申请上传链接失败: {res_data.get('msg')}")
                return None

            batch_id = res_data["data"]["batch_id"]
            upload_url = res_data["data"]["file_urls"][0]
            
            upload_headers = {}
            if res_data["data"].get("headers") and len(res_data["data"].get("headers", [])) > 0:
                upload_headers = res_data["data"]["headers"][0]

            logger.info(f"开始直传文件流...")
            with open(file_path, "rb") as f:
                upload_res = requests.put(upload_url, data=f, headers=upload_headers, timeout=120, proxies={"http": None, "https": None})
                upload_res.raise_for_status()

            logger.info(f"文件流直传成功，正在向 MinerU 轮询解析任务状态 (batch_id: {batch_id})...")

            query_url = f"{self.api_base_url}/extract-results/batch/{batch_id}"
            start_time = time.time()
            full_zip_url: Optional[str] = None

            while time.time() - start_time < max_poll_seconds:
                poll_res = requests.get(query_url, headers={"Authorization": f"Bearer {self.api_token}"}, timeout=20, proxies={"http": None, "https": None})
                if poll_res.status_code == 200:
                    poll_data = poll_res.json()
                    if poll_data.get("code") == 0 and poll_data.get("data"):
                        batch_info = poll_data["data"]
                        extract_result = batch_info.get("extract_result", [])
                        if extract_result:
                            task_item = extract_result[0]
                            state = task_item.get("state")
                            if state == "done":
                                full_zip_url = task_item.get("full_zip_url")
                                break
                            elif state == "failed":
                                err_msg = task_item.get("err_msg", "未知错误")
                                logger.error(f"MinerU 云端解析任务失败: {err_msg}")
                                return None

                time.sleep(3)

            if not full_zip_url:
                logger.error(f"MinerU 轮询超时 ({max_poll_seconds}s) 或未获取到 full_zip_url")
                return None

            try:
                zip_res = requests.get(full_zip_url, timeout=60, proxies={"http": None, "https": None})
                zip_res.raise_for_status()
            except Exception as dl_err:
                zip_res = requests.get(full_zip_url, timeout=60)
                zip_res.raise_for_status()

            with zipfile.ZipFile(io.BytesIO(zip_res.content)) as z:
                md_files = [name for name in z.namelist() if name.endswith("full.md") or name.endswith(".md")]
                if md_files:
                    target_filename = md_files[0]
                    with z.open(target_filename) as f_md:
                        markdown_str = f_md.read().decode("utf-8")
                        return markdown_str

        except Exception as e:
            logger.exception(f"调用 MinerU 官方 HTTP API 过程发生异常: {str(e)}")

        return None

    def parse(self, file_path: str, task_id: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"无法找到待解析文件: {file_path}")

        current_task_id = task_id or str(uuid.uuid4())
        file_name = os.path.basename(file_path)
        parse_mode = kwargs.get("parse_mode", "auto")

        task_output_dir = self.output_base_dir / current_task_id
        os.makedirs(task_output_dir, exist_ok=True)
        md_file_path = task_output_dir / "output.md"

        logger.info(f"MinerUParser: 启动云端提取流程 for {file_name}...")
        markdown_content = self._parse_via_cloud_api(
            file_path=file_path,
            task_id=current_task_id,
            model_version="vlm" if parse_mode in ["auto", "ocr"] else "pipeline"
        )
        
        is_api_success = bool(markdown_content)

        if not markdown_content:
            logger.warning(f"MinerU 解析失败或无返回。")
            raise RuntimeError(f"MinerU 解析失败: {file_name}")

        with open(md_file_path, "w", encoding="utf-8") as f:
            f.write(markdown_content)

        return {
            "task_id": current_task_id,
            "file_name": file_name,
            "parse_mode": parse_mode,
            "is_mineru_native": is_api_success,
            "md_file_path": str(md_file_path),
            "markdown_content": markdown_content,
            "page_count": 1 # MinerU 不原生提供页码划分
        }

mineru_parser = MinerUParser()
