import os
import io
import time
import uuid
import zipfile
import requests
from pathlib import Path
from typing import Dict, Any, Optional, List
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

    def reload_runtime_config(self) -> None:
        """同步 MinerU 单例配置，后续解析请求立即使用新值。"""
        self.api_token = settings.MINERU_API_TOKEN
        self.api_base_url = settings.MINERU_API_BASE_URL.rstrip("/")
        logger.info("MinerU OCR 配置已热更新。")

    @staticmethod
    def _get_runtime_config() -> tuple[str, str]:
        """按当前请求租户读取 MinerU 配置，避免单例在并发租户间串配置。"""
        from app.core.context import current_tenant_id
        from app.services.model_config_service import model_config_service

        values = model_config_service.get_values(current_tenant_id.get())
        return values["MINERU_API_TOKEN"], values["MINERU_API_BASE_URL"].rstrip("/")

    def check_availability(self) -> Dict[str, Any]:
        api_token, _ = self._get_runtime_config()
        has_token = bool(api_token and api_token.strip())
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

    def _get_http_session(self) -> requests.Session:
        """
        构造具备防御性配置的 HTTP Session：
        1. 自动忽略 SSL 证书校验警告 (verify=False)
        2. 设置浏览器标准 User-Agent，防止 Cloudflare/CDN 安全拦截
        3. 显式置空 proxies 防止 Windows 本地代理软件 (如 127.0.0.1:7892) 拦截并引发 UNEXPECTED_EOF 握手中断
        """
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        session = requests.Session()
        session.verify = False
        session.proxies = {"http": None, "https": None}
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        return session

    def _parse_via_cloud_api(
        self,
        file_path: str,
        task_id: str,
        model_version: str = "vlm",
        max_poll_seconds: int = 180
    ) -> Optional[str]:
        api_token, api_base_url = self._get_runtime_config()
        if not api_token:
            logger.warning("未配置 MINERU_API_TOKEN，无法发起云端 HTTP 接口调用。")
            return None

        file_name = os.path.basename(file_path)
        ext = os.path.splitext(file_name)[1].lower() or ".pdf"
        sanitized_name = f"doc_{task_id[:8].replace('-', '')}{ext}"
        
        headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json"
        }

        session = self._get_http_session()

        try:
            apply_url = f"{api_base_url}/file-urls/batch"
            apply_payload = {
                "files": [{"name": sanitized_name, "data_id": task_id}],
                "model_version": model_version,
                "is_ocr": True,
                "enable_table": True
            }
            logger.info(f"正在向 MinerU 云端 API 申请上传凭证 ({sanitized_name})")
            res = session.post(apply_url, headers=headers, json=apply_payload, timeout=30)
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
                upload_res = session.put(upload_url, data=f, headers=upload_headers, timeout=120)
                upload_res.raise_for_status()

            logger.info(f"文件流直传成功，正在向 MinerU 轮询解析任务状态 (batch_id: {batch_id})，最高等待可容受 600s...")

            query_url = f"{api_base_url}/extract-results/batch/{batch_id}"
            start_time = time.time()
            last_log_time = start_time
            full_zip_url: Optional[str] = None

            while time.time() - start_time < max_poll_seconds:
                elapsed_sec = int(time.time() - start_time)
                if time.time() - last_log_time >= 15:
                    logger.info(f"⌛ 正在等待 MinerU 深度 OCR 解构与转换... 已经过 {elapsed_sec} 秒 / 上限 {max_poll_seconds} 秒")
                    last_log_time = time.time()

                poll_res = session.get(query_url, headers={"Authorization": f"Bearer {api_token}"}, timeout=20)
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
                                logger.info(f"✅ MinerU 解析圆满完结（总耗时 {elapsed_sec}s），开始拉取精装 Markdown...")
                                break
                            elif state == "failed":
                                err_msg = task_item.get("err_msg", "未知错误")
                                logger.error(f"MinerU 云端解析任务失败: {err_msg}")
                                return None

                time.sleep(3)

            if not full_zip_url:
                logger.error(f"❌ MinerU 轮询极限超时 ({max_poll_seconds}s) 或未能捕获全量返回包！")
                return None

            try:
                zip_res = session.get(full_zip_url, timeout=60)
                zip_res.raise_for_status()
            except Exception as dl_err:
                zip_res = requests.get(full_zip_url, timeout=60, verify=False)
                zip_res.raise_for_status()

            with zipfile.ZipFile(io.BytesIO(zip_res.content)) as z:
                md_files = [name for name in z.namelist() if name.endswith("full.md") or name.endswith(".md")]
                if md_files:
                    target_filename = md_files[0]
                    with z.open(target_filename) as f_md:
                        markdown_str = f_md.read().decode("utf-8")
                        return markdown_str

        except Exception as e:
            logger.warning(f"调用 MinerU 官方 HTTP API 过程发生网络/SSL异常: {str(e)}")

        return None

    @staticmethod
    def _get_pdf_page_count(file_path: str) -> int:
        """
        获取 PDF 文档的物理总页数，非 PDF 文件返回 0。
        """
        ext = os.path.splitext(file_path)[1].lower()
        if ext != ".pdf":
            return 0
        try:
            import fitz
            doc = fitz.open(file_path)
            count = len(doc)
            doc.close()
            return count
        except Exception as e:
            logger.warning(f"无法读取 PDF 页数 ({file_path}): {e}")
            return 0

    @staticmethod
    def _split_pdf_into_chunks(
        file_path: str,
        max_pages_per_chunk: int,
        temp_dir: Path
    ) -> List[Dict[str, Any]]:
        """
        利用 PyMuPDF 将超过 max_pages_per_chunk 页的 PDF 按物理页码切割为多个子 PDF。

        Returns:
            List[Dict]: [{'chunk_path': str, 'start_page': int, 'end_page': int, 'chunk_index': int}]
        """
        import fitz
        doc = fitz.open(file_path)
        total_pages = len(doc)
        chunks = []

        chunk_index = 0
        for start in range(0, total_pages, max_pages_per_chunk):
            end = min(start + max_pages_per_chunk, total_pages)
            chunk_doc = fitz.open()
            chunk_doc.insert_pdf(doc, from_page=start, to_page=end - 1)

            sub_file_name = f"chunk_{chunk_index + 1}_p{start + 1}-{end}.pdf"
            sub_file_path = temp_dir / sub_file_name
            chunk_doc.save(str(sub_file_path))
            chunk_doc.close()

            chunks.append({
                "chunk_path": str(sub_file_path),
                "start_page": start + 1,
                "end_page": end,
                "chunk_index": chunk_index + 1
            })
            chunk_index += 1

        doc.close()
        return chunks

    def _parse_single_file_with_retries(
        self,
        file_path: str,
        base_task_id: str,
        max_retries: int = 2,
        parse_mode: str = "auto"
    ) -> str:
        """
        单个文件调用 MinerU 云端 API，具备 max_retries 次重试能力，成功则返回 markdown 内容。
        """
        file_name = os.path.basename(file_path)
        markdown_content: Optional[str] = None
        last_exception: Optional[Exception] = None

        total_attempts = max_retries + 1
        for attempt in range(1, total_attempts + 1):
            current_task_id = base_task_id if attempt == 1 else f"{base_task_id}_retry_{attempt - 1}"
            if attempt > 1:
                logger.warning(
                    f"🔄 MinerU 第 {attempt - 1} 次解析失败/无响应，正在进行第 {attempt - 1}/{max_retries} 次重试 ({file_name})..."
                )
                time.sleep(2)  # 重试间间隔 2 秒

            logger.info(f"MinerUParser: 启动云端提取流程 (尝试 {attempt}/{total_attempts}) for {file_name}...")
            try:
                markdown_content = self._parse_via_cloud_api(
                    file_path=file_path,
                    task_id=current_task_id,
                    model_version="vlm" if parse_mode in ["auto", "ocr"] else "pipeline",
                )
                if markdown_content and markdown_content.strip():
                    if attempt > 1:
                        logger.info(f"✅ MinerU 第 {attempt - 1} 次重试解析成功: {file_name}")
                    break
                else:
                    logger.warning(f"⚠️ MinerU 第 {attempt} 次尝试未获取到有效的 Markdown 内容")
            except Exception as e:
                last_exception = e
                logger.warning(f"⚠️ MinerU 第 {attempt} 次尝试发生异常: {str(e)}")

        if not markdown_content or not markdown_content.strip():
            logger.error(f"❌ MinerU 在重试 {max_retries} 次后依然解析失败: {file_name}")
            err_msg = f"MinerU 解析失败 (在重试 {max_retries} 次后仍无有效输出): {file_name}"
            if last_exception:
                raise RuntimeError(err_msg) from last_exception
            raise RuntimeError(err_msg)

        return markdown_content

    def parse(
        self,
        file_path: str,
        task_id: Optional[str] = None,
        max_retries: int = 2,
        max_pages_per_chunk: int = 180,
        **kwargs
    ) -> Dict[str, Any]:
        """
        使用 MinerU 官方云端 API 解析文档。
        支持解析失败时自动重试，并针对超长 PDF (>180页) 自动分片分卷解析与无缝合并。

        Args:
            file_path: 待解析的文件路径
            task_id: 任务 ID (可选)
            max_retries: 解析失败时的最大重试次数，默认为 2 次（即最多尝试 3 次）
            max_pages_per_chunk: 单批次最大页数阈值，默认为 180 页（低于 200 页 API 限制，安全缓冲）
            **kwargs: 其他解析参数 (如 parse_mode)

        Returns:
            Dict[str, Any]: 包含解析出的 Markdown 内容及元数据的字典

        Raises:
            FileNotFoundError: 文件不存在时抛出
            RuntimeError: 所有重试均失败后抛出
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"无法找到待解析文件: {file_path}")

        base_task_id = task_id or str(uuid.uuid4())
        file_name = os.path.basename(file_path)
        parse_mode = kwargs.get("parse_mode", "auto")

        total_pdf_pages = self._get_pdf_page_count(file_path)

        # 校验是否为超长 PDF 并触发自动拆切片解析
        if total_pdf_pages > max_pages_per_chunk:
            chunk_count = (total_pdf_pages + max_pages_per_chunk - 1) // max_pages_per_chunk
            logger.info(
                f"📄 PDF 文档页数 ({total_pdf_pages} 页) 超过 MinerU 单次限制 ({max_pages_per_chunk} 页)，"
                f"启动自动拆分分卷解析策略 (预计分为 {chunk_count} 个批次)..."
            )

            temp_split_dir = self.output_base_dir / base_task_id / "split_temp"
            os.makedirs(temp_split_dir, exist_ok=True)

            try:
                chunks_info = self._split_pdf_into_chunks(file_path, max_pages_per_chunk, temp_split_dir)
                combined_markdowns = []

                for chunk in chunks_info:
                    c_path = chunk["chunk_path"]
                    s_page = chunk["start_page"]
                    e_page = chunk["end_page"]
                    c_idx = chunk["chunk_index"]

                    logger.info(f"🚀 开始解析分卷 {c_idx}/{len(chunks_info)} (页码: {s_page}~{e_page})...")
                    sub_task_id = f"{base_task_id}_chunk_{c_idx}"
                    sub_md = self._parse_single_file_with_retries(
                        file_path=c_path,
                        base_task_id=sub_task_id,
                        max_retries=max_retries,
                        parse_mode=parse_mode,
                    )

                    combined_markdowns.append(
                        f"\n\n<!-- MinerU Chunk {c_idx}/{len(chunks_info)} (Pages {s_page}-{e_page}) -->\n\n"
                        + sub_md.strip()
                    )

                markdown_content = "\n\n".join(combined_markdowns).strip()
                logger.info(f"✅ 超长 PDF {file_name} 全部 {len(chunks_info)} 个分卷解析完成并已无缝合并！")
            finally:
                if os.path.exists(temp_split_dir):
                    import shutil
                    shutil.rmtree(temp_split_dir, ignore_errors=True)
        else:
            # 正常单文件解析流程
            markdown_content = self._parse_single_file_with_retries(
                file_path=file_path,
                base_task_id=base_task_id,
                max_retries=max_retries,
                parse_mode=parse_mode,
            )

        task_output_dir = self.output_base_dir / base_task_id
        os.makedirs(task_output_dir, exist_ok=True)
        md_file_path = task_output_dir / "output.md"

        with open(md_file_path, "w", encoding="utf-8") as f:
            f.write(markdown_content)

        return {
            "task_id": base_task_id,
            "file_name": file_name,
            "parse_mode": parse_mode,
            "is_mineru_native": True,
            "md_file_path": str(md_file_path),
            "markdown_content": markdown_content,
            "page_count": total_pdf_pages or 1,
        }

mineru_parser = MinerUParser()
