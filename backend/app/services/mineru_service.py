import os
import io
import time
import uuid
import re
import zipfile
import requests
from pathlib import Path
from typing import List, Dict, Any, Optional
from loguru import logger
import docx

from app.core.config import settings

# 默认分块最大长度与重叠字数
MAX_CHUNK_SIZE: int = 1500
CHUNK_OVERLAP: int = 200

# 1 级大章识别正则模式匹配库（招投标常见章节风格）
MAJOR_CHAPTER_PATTERNS: List[re.Pattern] = [
    re.compile(r'^\s*[*#]*\s*(第[一二三四五六七八九十百零\d]+[章节部分篇].*)'),
    re.compile(r'^\s*[*#]*\s*(附[件录表][一二三四五六七八九十\dA-Za-z]+.*)'),
]

# 中文汉字序号二级标题识别（如"一、项目说明"、"二、评分标准："、"三、技术要求"）
ORDINAL_HEADING_PATTERN: re.Pattern = re.compile(r'^[一二三四五六七八九十百]+、')



class MinerUService:
    """
    MinerU 官方 HTTP API 智能文档解析服务模块。
    参考官方 API 接口文档: https://mineru.net/apiManage/docs
    
    工作流程:
    1. 申请批次上传预签名 URL (`POST /api/v4/file-urls/batch`)
    2. 物理文件流直传 (`PUT {upload_url}`)
    3. 异步任务进度轮询 (`GET /api/v4/extract/task/batch/{batch_id}`)
    4. 自动解包全量 Markdown (`full_zip_url` -> `full.md`)
    """

    def __init__(self, output_base_dir: Optional[str] = None):
        """
        初始化 MinerU 在线 API 服务实例
        :param output_base_dir: 输出 Markdown 及附件的默认基础目录
        """
        if output_base_dir:
            self.output_base_dir = Path(output_base_dir)
        else:
            base_dir = Path(__file__).resolve().parent.parent.parent
            self.output_base_dir = base_dir / "uploads" / "mineru_output"

        os.makedirs(self.output_base_dir, exist_ok=True)
        self.api_token = settings.MINERU_API_TOKEN
        self.api_base_url = settings.MINERU_API_BASE_URL.rstrip("/")

    def check_availability(self) -> Dict[str, Any]:
        """
        检测 MinerU 官方 Cloud API 密钥配置与健康状态
        :return: 包含可用标志、API Token 状态及说明的字典
        """
        has_token = bool(self.api_token and self.api_token.strip())
        
        if has_token:
            logger.info("MinerU 官方 API Token 已成功配置。")
            return {
                "is_installed": True,
                "has_api_token": True,
                "executable_path": "MinerU-Online-HTTP-API",
                "supported_formats": ["pdf", "docx", "doc", "ppt", "pptx", "xls", "xlsx", "png", "jpg", "html"],
                "message": "MinerU 官方在线 HTTP API 服务准备就绪（已配置 MINERU_API_TOKEN）。"
            }

        logger.warning("未在 .env 中检测到 MINERU_API_TOKEN，请参考 https://mineru.net/apiManage/docs 填入 Token。")
        return {
            "is_installed": False,
            "has_api_token": False,
            "executable_path": None,
            "supported_formats": ["docx", "doc"],
            "message": "未配置 MINERU_API_TOKEN，解析服务当前将使用内置 Word/Markdown 结构化抽取回退逻辑。"
        }

    def parse_via_cloud_api(
        self,
        file_path: str,
        task_id: str,
        model_version: str = "vlm",
        max_poll_seconds: int = 120
    ) -> Optional[str]:
        """
        基于官方 MinerU API (v4) 完成本地文件远程在线解析:
        参考文档: https://mineru.net/apiManage/docs
        
        步骤:
        1. POST /api/v4/file-urls/batch 申请预签名上传 URL 与 batch_id
        2. PUT {upload_url} 上传物理文件流
        3. GET /api/v4/extract/task/batch/{batch_id} 轮询提取进度直到 state == "done"
        4. 下载 full_zip_url 提取 zip 内的 full.md 文件
        """
        if not self.api_token:
            logger.warning("未配置 MINERU_API_TOKEN，无法发起云端 HTTP 接口调用。")
            return None

        file_name = os.path.basename(file_path)
        ext = os.path.splitext(file_name)[1].lower() or ".pdf"
        # 使用安全的纯 ASCII 纯字母数字文件名申请预签名 URL，防止 OSS 签名中文校验抛出 403 SignatureDoesNotMatch
        sanitized_name = f"doc_{task_id[:8].replace('-', '')}{ext}"
        
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json"
        }

        try:
            # 步骤 1: 申请预签名上传链接
            apply_url = f"{self.api_base_url}/file-urls/batch"
            apply_payload = {
                "files": [{"name": sanitized_name, "data_id": task_id}],
                "model_version": model_version
            }
            logger.info(f"正在向 MinerU 云端 API 申请上传凭证 ({sanitized_name}): {apply_url}")
            res = requests.post(apply_url, headers=headers, json=apply_payload, timeout=30)
            res.raise_for_status()
            res_data = res.json()

            if res_data.get("code") != 0:
                logger.error(f"MinerU 申请上传链接失败: {res_data.get('msg')}")
                return None

            batch_id = res_data["data"]["batch_id"]
            upload_url = res_data["data"]["file_urls"][0]
            # 获取凭证响应中返回的底层真实任务 ID，用于后续精确状态轮询
            task_ids = res_data["data"].get("task_ids", [])
            real_task_id = task_ids[0] if task_ids else task_id
            
            # 必须带上 API 返回的预签名指定 headers (如 Content-Type)，避免阿里云 OSS 返回 403 SignatureDoesNotMatch
            upload_headers = {}
            if res_data["data"].get("headers") and len(res_data["data"].get("headers", [])) > 0:
                upload_headers = res_data["data"]["headers"][0]

            logger.info(f"成功分配 MinerU 任务 ID [{real_task_id}] (批次: {batch_id})，开始直传文件流 (Headers: {upload_headers})...")

            # 步骤 2: 上传文件流至预签名 URL (严格带上返回的 Content-Type 请求头)
            with open(file_path, "rb") as f:
                upload_res = requests.put(upload_url, data=f, headers=upload_headers, timeout=120)
                upload_res.raise_for_status()

            logger.info(f"文件流直传成功，正在向 MinerU 轮询解析任务状态 (batch_id: {batch_id})...")

            # 步骤 3: 正确轮询 MinerU v4 批次接口 GET /api/v4/extract-results/batch/{batch_id}
            query_url = f"{self.api_base_url}/extract-results/batch/{batch_id}"
            start_time = time.time()
            full_zip_url: Optional[str] = None

            while time.time() - start_time < max_poll_seconds:
                poll_res = requests.get(query_url, headers={"Authorization": f"Bearer {self.api_token}"}, timeout=20)
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
                                logger.info(f"⚡ MinerU 云端 API 解析完成！Zip 下载链接: {full_zip_url}")
                                break
                            elif state == "failed":
                                err_msg = task_item.get("err_msg", "未知错误")
                                logger.error(f"MinerU 云端解析任务失败: {err_msg}")
                                return None

                time.sleep(3)

            if not full_zip_url:
                logger.error(f"MinerU 轮询超时 ({max_poll_seconds}s) 或未获取到 full_zip_url")
                return None

            # 步骤 4: 下载结果压缩包并解压缩 full.md (优先绕过本地系统代理，防 SSLEOFError)
            try:
                zip_res = requests.get(full_zip_url, timeout=60, proxies={"http": None, "https": None})
                zip_res.raise_for_status()
            except Exception as dl_err:
                logger.warning(f"直连下载 MinerU 压缩包触发异常 ({dl_err})，尝试使用默认网络模式重试...")
                zip_res = requests.get(full_zip_url, timeout=60)
                zip_res.raise_for_status()

            with zipfile.ZipFile(io.BytesIO(zip_res.content)) as z:
                # 查找压缩包中的 full.md 文件
                md_files = [name for name in z.namelist() if name.endswith("full.md") or name.endswith(".md")]
                if md_files:
                    target_filename = md_files[0]
                    with z.open(target_filename) as f_md:
                        markdown_str = f_md.read().decode("utf-8")
                        logger.info(f"成功解包获取 MinerU 结果 Markdown ({len(markdown_str)} 字)")
                        return markdown_str

        except Exception as e:
            logger.exception(f"调用 MinerU 官方 HTTP API 过程发生异常: {str(e)}")

        return None

    @staticmethod
    def _is_table_caption(text: str, paragraph: Any) -> bool:
        """
        判断一个段落是否是紧接在它之后的表格的标题/说明。
        判定规则（满足任一即视为表格标题）：
        1. 文本以「表」+序号开头（如 "表1 资质要求"、"表二 评分标准"）
        2. 段落样式为 Caption / 表题 类型
        3. 文本较短（≤60字）且段落中所有有效 Run 均为粗体
        4. 文本较短（≤60字）且以中英文冒号「：/ :」结尾（常见引导语如"资质要求："）
        5. 文本极短（≤30字）且不含任何句末标点（。；？！.;?!）
           —— 通常是纯名词短语型标题，如"施工材料清单"、"评分标准明细"
        """
        if not text or len(text) > 80:
            return False

        # 规则1：以「表」+ 数字/汉字序号 开头，如"表1"、"表二"
        if re.match(r'^表\s*[\d一二三四五六七八九十百]+', text):
            return True

        # 规则2：段落样式名称包含 caption / 表题 / table caption 关键词
        try:
            style_name = paragraph.style.name.lower() if paragraph.style else ""
            if any(kw in style_name for kw in ("caption", "表题", "table caption")):
                return True
        except Exception:
            pass

        # 规则3：全部有效 Run 均为粗体（且文本不超过 60 字）
        if len(text) <= 60:
            try:
                valid_runs = [r for r in paragraph.runs if r.text.strip()]
                if valid_runs and all(r.bold for r in valid_runs):
                    return True
            except Exception:
                pass

        # 规则4：文本 ≤60 字且以中英文冒号结尾
        # 典型场景："以下为评分标准：" / "资质要求如下："
        if len(text) <= 60 and (text.endswith("：") or text.endswith(":")):
            return True

        # 规则5：文本极短（≤30字）且不含任何句末标点
        # 判断逻辑：纯名词短语标题通常不包含"。；？！"等收句标点
        # 典型场景："施工材料清单"、"评分标准明细"、"投标人资格要求"
        SENTENCE_END_PUNCTUATIONS = ("。", "；", "？", "！", ".", ";", "?", "!")
        if len(text) <= 30 and not any(p in text for p in SENTENCE_END_PUNCTUATIONS):
            return True

        return False


    def _convert_docx_to_markdown(self, docx_path: str) -> str:
        """
        回退模式：使用 python-docx 将 Word (.docx) 快速转换为 Markdown 文本。
        核心特性：
        - 顺序迭代 doc.element.body 子节点，保持段落与表格的原始交错上下文顺序
        - 前瞻检测（Look-ahead）识别紧接在表格之前的「表格标题段落」，
          以 **加粗** 格式输出，在 Markdown 中明确关联段落与表格
        """
        if not os.path.exists(docx_path):
            raise FileNotFoundError(f"未找到指定的 Word 文件: {docx_path}")

        logger.info(f"开始使用内置 Word 解析器转换文档: {docx_path}")
        doc = docx.Document(docx_path)
        md_lines: List[str] = []

        # 顺序迭代 doc.element.body 下的子节点，精准保持段落与表格在文档中的原始交错上下文顺序
        from docx.text.paragraph import Paragraph
        from docx.table import Table

        # 将 body children 收集为列表，以支持按索引前瞻（look-ahead）
        body_children = list(doc.element.body)

        for i, child in enumerate(body_children):
            if child.tag.endswith('p'):
                p = Paragraph(child, doc)
                text = p.text.strip()
                if not text:
                    continue

                # ---- 前瞻检测：判断此段落是否为紧跟其后的表格的标题 ----
                # 跳过后续空白段落，找到下一个非空元素
                is_caption = False
                for next_child in body_children[i + 1:]:
                    if next_child.tag.endswith('p'):
                        # 遇到非空段落则打断（有其他文本段介入，不是紧接的表格标题）
                        next_p = Paragraph(next_child, doc)
                        if next_p.text.strip():
                            break
                        # 空段落可忽略，继续向后找
                    elif next_child.tag.endswith('tbl'):
                        # 找到紧接的表格，检查当前段落是否符合表格标题特征
                        is_caption = self._is_table_caption(text, p)
                        break

                style_name = p.style.name.lower() if p.style else ""
                if "heading 1" in style_name:
                    md_lines.append(f"# {text}\n")
                elif "heading 2" in style_name:
                    md_lines.append(f"## {text}\n")
                elif "heading 3" in style_name:
                    md_lines.append(f"### {text}\n")
                elif ORDINAL_HEADING_PATTERN.match(text):
                    # 汉字序号格式（一、二、三、...）识别为 Markdown 二级标题
                    # 优先级高于表格标题加粗，使文档层次结构更清晰
                    md_lines.append(f"## {text}\n")
                    logger.debug(f"识别到汉字序号二级标题: 「{text}」")
                elif is_caption:
                    # 非序号格式的表格标题：加粗显示，与下方表格形成明确的视觉关联
                    md_lines.append(f"\n**{text}**")
                    logger.debug(f"识别到表格标题段落: 「{text}」")
                else:
                    if any(pat.match(text) for pat in MAJOR_CHAPTER_PATTERNS):
                        md_lines.append(f"# {text}\n")
                    else:
                        md_lines.append(f"{text}\n")


            elif child.tag.endswith('tbl'):
                table = Table(child, doc)
                if not table.rows:
                    continue
                md_lines.append("\n")
                headers = [cell.text.strip().replace("\n", " ") for cell in table.rows[0].cells]
                md_lines.append("| " + " | ".join(headers) + " |")
                md_lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
                
                for row in table.rows[1:]:
                    row_cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
                    md_lines.append("| " + " | ".join(row_cells) + " |")
                md_lines.append("\n")

        return "\n".join(md_lines)

    def _parse_markdown_into_sections(self, markdown_text: str) -> List[Dict[str, Any]]:
        """
        根据 Markdown 中的标题层级和正则表达式，将文本切分为结构化的大章段落
        """
        lines = markdown_text.splitlines()
        sections: List[Dict[str, Any]] = []
        current_title = "前言/概要"
        current_content_lines: List[str] = []

        for line in lines:
            stripped = line.strip()
            is_header = False

            if stripped.startswith("# ") or stripped.startswith("## "):
                clean_header = stripped.lstrip("#").strip()
                is_header = True
            elif any(pat.match(stripped) for pat in MAJOR_CHAPTER_PATTERNS):
                clean_header = stripped.strip()
                is_header = True

            if is_header:
                if current_content_lines:
                    content_str = "\n".join(current_content_lines).strip()
                    if content_str:
                        sections.append({
                            "title": current_title,
                            "text": content_str,
                            "page_start": 1,
                            "content_type": "chapter_block"
                        })
                current_title = clean_header
                current_content_lines = [stripped]
            else:
                current_content_lines.append(line)

        if current_content_lines:
            content_str = "\n".join(current_content_lines).strip()
            if content_str:
                sections.append({
                    "title": current_title,
                    "text": content_str,
                    "page_start": 1,
                    "content_type": "chapter_block"
                })

        return sections

    def parse_file(
        self,
        file_path: str,
        task_id: Optional[str] = None,
        parse_mode: str = "auto"
    ) -> Dict[str, Any]:
        """
        核心文件解析入口
        :param file_path: 目标文件完整绝对路径
        :param task_id: 任务唯一标识，如果不传则自动分配
        :param parse_mode: 解析模式 (auto/txt/ocr)
        :return: 提取结果字典
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"无法找到待解析文件: {file_path}")

        current_task_id = task_id or str(uuid.uuid4())
        file_name = os.path.basename(file_path)
        ext = os.path.splitext(file_name)[1].lower()

        # 为该任务创建专属的输出目录
        task_output_dir = self.output_base_dir / current_task_id
        os.makedirs(task_output_dir, exist_ok=True)
        md_file_path = task_output_dir / "output.md"

        markdown_content = ""
        is_api_success = False

        # 分支逻辑：处理 Word 文档 (.docx/.doc) 时暂不使用 MinerU，直接启用优化后的 python-docx 原位置交错解析
        if ext in [".docx", ".doc"]:
            logger.info(f"📄 监测到 Word 文档 (`{file_name}`)，直接启用 python-docx 原位置交错解析...")
            try:
                markdown_content = self._convert_docx_to_markdown(file_path)
            except Exception as ex:
                logger.error(f"内置 Word 解析器失败: {str(ex)}")
                markdown_content = f"# 文件解析失败通知\n\n解析文件 `{file_name}` 时引发异常: {str(ex)}"
        else:
            # 非 Word 文件 (如 PDF)：优先使用 MinerU 官方在线 HTTP API 提取
            if self.api_token:
                logger.info("启动 MinerU 官方在线 HTTP API 提取流程...")
                markdown_content = self.parse_via_cloud_api(
                    file_path=file_path,
                    task_id=current_task_id,
                    model_version="vlm" if parse_mode in ["auto", "ocr"] else "pipeline"
                )
                if markdown_content:
                    is_api_success = True
            else:
                logger.warning(f"由于未配置 MINERU_API_TOKEN 且无云端 API 响应，生成标准结构化回退结果。")
                markdown_content = (
                    f"# 文档解析结果 ({file_name})\n\n"
                    f"> 注意：请在 `.env` 中配置 `MINERU_API_TOKEN` 以解锁完整 MinerU 高精度云端解析功能。\n"
                    f"> 参考文档: https://mineru.net/apiManage/docs\n\n"
                    f"## 基础元数据\n"
                    f"- **文件名**: {file_name}\n"
                    f"- **解析模式**: {parse_mode}\n"
                    f"- **任务 ID**: {current_task_id}\n"
                )

        # 写入物理磁盘中的 Markdown 文件
        with open(md_file_path, "w", encoding="utf-8") as f:
            f.write(markdown_content)

        logger.info(f"Markdown 解析文件已成功保存至: {md_file_path}")

        # 切分并归组章节
        sections = self._parse_markdown_into_sections(markdown_content)

        return {
            "task_id": current_task_id,
            "file_name": file_name,
            "parse_mode": parse_mode,
            "is_mineru_native": is_api_success,
            "md_file_path": str(md_file_path),
            "markdown_content": markdown_content,
            "page_count": len(sections),
            "sections": sections,
            "images": []
        }


# 单例导出
mineru_service = MinerUService()


