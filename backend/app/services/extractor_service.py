import os
import re
import logging
from typing import List, Dict, Any, Optional
from langchain_core.documents import Document
import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

# ========== 切分策略常量 ==========
MAX_CHUNK_SIZE: int = 1200
CHUNK_OVERLAP: int = 200

MAJOR_CHAPTER_PATTERNS: List[re.Pattern] = [
    re.compile(r'^\s*[*#]*\s*(第[一二三四五六七八九十百零\d]+[章节部分篇].*)'),
    re.compile(r'^\s*[*#]*\s*(附[件录表][一二三四五六七八九十\dA-Za-z]+.*)'),
]
CHAPTER_PATTERNS = MAJOR_CHAPTER_PATTERNS

class ExtractorService:
    """
    文档提取总调度工厂 (Orchestrator)。
    负责根据文件类型和环境智能选择合适的 Parser，并统一执行通用的语义切分 (Chunking)。
    """
    def __init__(self):
        pass

    def _get_mineru_parser(self):
        from app.services.parsers.mineru_parser import mineru_parser
        return mineru_parser

    def _get_docling_parser(self):
        from app.services.parsers.docling_parser import docling_parser
        return docling_parser

    def _get_docx_parser(self):
        from app.services.parsers.docx_parser import docx_parser
        return docx_parser

    def is_scanned_pdf(self, file_path: str, check_pages: int = 3) -> bool:
        """
        使用 PyMuPDF 检测 PDF 是否为纯图片的扫描件。
        判断逻辑：抽取前几页，如果文本极少但有图片，则判定为扫描件。
        """
        if not file_path.lower().endswith(".pdf"):
            return False
        try:
            doc = fitz.open(file_path)
            total_pages = len(doc)
            check_count = min(check_pages, total_pages)
            
            total_text_len = 0
            has_images = False
            
            for i in range(check_count):
                page = doc[i]
                text = page.get_text().strip()
                total_text_len += len(text)
                if len(page.get_images()) > 0:
                    has_images = True
                    
            avg_text = total_text_len / check_count
            if avg_text < 50 and has_images:
                logger.warning(f"检测到文件可能为扫描件 (平均文本长度: {avg_text})")
                return True
                
            return False
        except Exception as e:
            logger.error(f"检测扫描件出错: {str(e)}")
            return False

    def convert_doc_to_docx(self, doc_path: str) -> str:
        import subprocess
        docx_path = doc_path + "x"
        if os.path.exists(docx_path):
            return docx_path
            
        try:
            logger.info(f"开始使用 LibreOffice 转换 .doc 到 .docx: {doc_path}")
            cmd = [
                "soffice", "--headless", "--convert-to", "docx",
                doc_path, "--outdir", os.path.dirname(doc_path)
            ]
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"LibreOffice 转换失败: {result.stderr}")
                 
            if not os.path.exists(docx_path):
                raise RuntimeError("转换命令执行成功，但未生成目标 .docx 文件")
                 
            logger.info(f"转换成功: {docx_path}")
            return docx_path
        except Exception as e:
            logger.error(f".doc 转 .docx 失败: {str(e)}")
            raise e

    def _detect_major_chapter_in_line(self, line: str) -> Optional[str]:
        """
        判断单行文本是否为 1 级大章标题 (如 第一章 投标邀请、第四章 项目需求、附件一 等)。
        支持识别内嵌在块中的标题行，同时过滤掉常见的交叉引用句。
        """
        clean = line.replace('*', '').replace('#', '').strip()
        if not clean or len(clean) > 100:
            return None
        if re.search(r'\d+\s*$', clean):
            return None
        if re.search(r'(详见|参见|遵循|依据|见)\s*第[一二三四五六七八九十\d]+[章节]', clean):
            return None
        for pattern in MAJOR_CHAPTER_PATTERNS:
            match = pattern.search(clean)
            if match:
                return clean
        return None

    def _group_markdown_text_by_chapter(self, markdown_text: str) -> List[Dict[str, Any]]:
        """
        将纯 Markdown 文本按 1 级大章 (第一章、第二章...) 进行全局归置与拼接。
        通过逐行扫描，将内容重新聚合到大章级别，方便后续进行自适应切片。
        """
        grouped_chapters: Dict[str, Dict[str, Any]] = {}
        chapter_order: List[str] = []
        current_chapter: str = "无章节/正文"

        lines = markdown_text.split('\n')
        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue

            line_chap = self._detect_major_chapter_in_line(line_str)
            if line_chap:
                current_chapter = line_chap

            if current_chapter not in grouped_chapters:
                chapter_order.append(current_chapter)
                grouped_chapters[current_chapter] = {
                    "title": current_chapter,
                    "text": line_str,
                    "page_start": 1,
                    "content_type": "chapter_block",
                    "trace_info": {
                        "chapter": current_chapter,
                        "headings": [current_chapter],
                        "element_label": "text"
                    }
                }
            else:
                grouped_chapters[current_chapter]["text"] += "\n" + line_str

        result_chapters: List[Dict[str, Any]] = []
        for title in chapter_order:
            block = grouped_chapters[title]
            if block["text"].strip():
                result_chapters.append(block)

        return result_chapters

    def _extract_text_and_table_blocks(self, text: str) -> List[Dict[str, Any]]:
        """
        将章节文本精准拆解为【普通文本段落块】与【完整的 Markdown 表格原子块】。
        表格块 (以 '|' 开头的连贯表格行) 将被赋予最高优先级保护，保证分块时不跨行、不跨表截断。
        """
        lines = text.splitlines()
        blocks: List[Dict[str, Any]] = []
        
        current_text_lines: List[str] = []
        current_table_lines: List[str] = []
        in_table = False

        for line in lines:
            stripped = line.strip()
            is_table_line = (
                stripped.startswith("|") and 
                (stripped.endswith("|") or "|" in stripped[1:]) and
                len(stripped) > 2
            )
            
            if is_table_line:
                if not in_table:
                    if current_text_lines:
                        blocks.append({"type": "text", "content": "\n".join(current_text_lines)})
                        current_text_lines = []
                    in_table = True
                current_table_lines.append(line)
            else:
                if in_table:
                    if current_table_lines:
                        blocks.append({"type": "table", "content": "\n".join(current_table_lines)})
                        current_table_lines = []
                    in_table = False
                current_text_lines.append(line)

        if current_table_lines:
            blocks.append({"type": "table", "content": "\n".join(current_table_lines)})
        if current_text_lines:
            blocks.append({"type": "text", "content": "\n".join(current_text_lines)})

        return blocks

    def _adaptive_split_chapter(self, chapter: Dict[str, Any], start_index: int) -> List[Document]:
        """
        对单个大章进行自适应分块：
        - 优先以二级标题 (##) 作为切分边界，保证同一二级标题下的内容尽量在同一分块内。
        - 保护表格与其上下文尽量在同一块中，禁止表格单独成块剥离上下文。
        - 容忍包含表格或短前置文本的 Chunk 适度超过 MAX_CHUNK_SIZE，避免切碎上下文。
        """
        from langchain_text_splitters import RecursiveCharacterTextSplitter
        
        docs: List[Document] = []
        chapter_text = chapter["text"].strip()
        
        if not chapter_text:
            return docs
        
        chapter_title = chapter["title"]
        
        if len(chapter_text) <= MAX_CHUNK_SIZE:
            docs.append(Document(
                page_content=chapter_text,
                metadata={
                    "section_title": chapter_title,
                    "chunk_index": start_index,
                    "page_num": chapter["page_start"],
                    "content_type": chapter["content_type"],
                    "trace_info": chapter["trace_info"],
                    "source": "",
                }
            ))
        else:
            logger.info(
                f"章节 [{chapter_title}] 文本长度 {len(chapter_text)} 字 > {MAX_CHUNK_SIZE}，"
                f"启动语义聚类及表格防割裂分块。"
            )
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=MAX_CHUNK_SIZE,
                chunk_overlap=CHUNK_OVERLAP,
                separators=["\n## ", "\n\n", "\n", "。", "；", ".", " "],
                length_function=len,
            )

            lines = chapter_text.split('\n')
            h2_sections = []
            curr_sec = []
            for line in lines:
                if line.strip().startswith("## "):
                    if curr_sec:
                        h2_sections.append("\n".join(curr_sec))
                        curr_sec = []
                curr_sec.append(line)
            if curr_sec:
                h2_sections.append("\n".join(curr_sec))

            sub_texts: List[str] = []
            current_chunk_parts: List[str] = []
            current_chunk_len = 0

            for h2_sec in h2_sections:
                h2_sec_stripped = h2_sec.strip()
                if not h2_sec_stripped:
                    continue
                
                if current_chunk_len + len(h2_sec_stripped) <= MAX_CHUNK_SIZE:
                    current_chunk_parts.append(h2_sec_stripped)
                    current_chunk_len += len(h2_sec_stripped)
                    continue
                
                if current_chunk_len > 300:
                    sub_texts.append("\n\n".join(current_chunk_parts))
                    current_chunk_parts = []
                    current_chunk_len = 0
                
                if current_chunk_len + len(h2_sec_stripped) <= MAX_CHUNK_SIZE:
                    current_chunk_parts.append(h2_sec_stripped)
                    current_chunk_len += len(h2_sec_stripped)
                else:
                    blocks = self._extract_text_and_table_blocks(h2_sec_stripped)
                    for b in blocks:
                        b_type = b["type"]
                        b_content = b["content"].strip()
                        if not b_content:
                            continue
                        
                        if b_type == "table":
                            if current_chunk_len + len(b_content) > MAX_CHUNK_SIZE and current_chunk_len > 300:
                                sub_texts.append("\n\n".join(current_chunk_parts))
                                current_chunk_parts = []
                                current_chunk_len = 0
                            
                            current_chunk_parts.append(b_content)
                            current_chunk_len += len(b_content)
                        else:
                            splits = splitter.split_text(b_content)
                            for s in splits:
                                if current_chunk_len + len(s) > MAX_CHUNK_SIZE and current_chunk_len > 300:
                                    sub_texts.append("\n\n".join(current_chunk_parts))
                                    current_chunk_parts = [s]
                                    current_chunk_len = len(s)
                                else:
                                    current_chunk_parts.append(s)
                                    current_chunk_len += len(s)

            if current_chunk_parts:
                sub_texts.append("\n\n".join(current_chunk_parts))

            for j, sub_text in enumerate(sub_texts):
                docs.append(Document(
                    page_content=sub_text,
                    metadata={
                        "section_title": chapter_title,
                        "chunk_index": start_index + j,
                        "page_num": chapter["page_start"],
                        "content_type": chapter["content_type"],
                        "trace_info": chapter["trace_info"],
                        "source": "",
                    }
                ))
        
        return docs

    def parse_and_chunk(self, file_path: str) -> List[Document]:
        """
        核心调度与切片入口：根据策略模式 (Strategy Pattern) 选择合适的 Parser
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")

        file_name = os.path.basename(file_path)
        ext = os.path.splitext(file_name)[1].lower()

        # 1. 预处理 Word 格式
        if ext == ".doc":
            file_path = self.convert_doc_to_docx(file_path)
            ext = ".docx"

        parser = None
        
        # 2. 路由逻辑：选择解析策略
        if ext == ".docx":
            logger.info(f"✅ 路由到 DocxParser: {file_name}")
            parser = self._get_docx_parser()
        else:
            # 对于 PDF，检查 MinerU 是否可用
            mineru = self._get_mineru_parser()
            if mineru.check_availability().get("is_installed"):
                logger.info(f"✅ 路由到 MinerUParser (主引擎): {file_name}")
                parser = mineru
            else:
                logger.info(f"⚠️ MinerU 不可用，回退路由到 DoclingParser (备用引擎): {file_name}")
                parser = self._get_docling_parser()

        # 3. 执行物理层提取 (统一返回带有 Markdown 文本的字典)
        parse_result = parser.parse(file_path)
        md_text = parse_result.get("markdown_content", "")
        md_file_path = parse_result.get("md_file_path", "")

        if not md_text or not md_text.strip():
            raise RuntimeError(f"解析器返回空文本: {file_name}")

        # 4. 执行大章归组 (公共 Chunking 逻辑)
        chapters = self._group_markdown_text_by_chapter(md_text)
        
        # 5. 自适应再分块与元数据注入
        final_docs: List[Document] = []
        chunk_index = 0
        for chapter in chapters:
            sub_docs = self._adaptive_split_chapter(chapter, start_index=chunk_index)
            for doc in sub_docs:
                doc.metadata["source"] = file_path
                doc.metadata["md_file_path"] = md_file_path
            final_docs.extend(sub_docs)
            chunk_index += len(sub_docs)
            
        logger.info(f"文档切分完成: {len(chapters)} 个大章 → {len(final_docs)} 个 Chunk。")
        return final_docs

# 单例导出
extractor_service = ExtractorService()
