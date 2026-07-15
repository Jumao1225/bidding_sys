import os
import re
import logging
from typing import List, Dict, Any, Optional
from langchain_core.documents import Document
import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

# ========== 切分策略常量 ==========
# 单块最大字数阈值，超过此值的章节将被自适应再分块 (1200 为最佳 RAG 召回长度)
MAX_CHUNK_SIZE: int = 1200
# 再分块时的重叠区域字数，确保切断点处上下文不丢失
CHUNK_OVERLAP: int = 200

# 招标文件大章标题正则模式列表（仅包含真正的 1 级大章与附件/附录）
MAJOR_CHAPTER_PATTERNS: List[re.Pattern] = [
    # 第一章、第二节、第三部分、第四篇
    re.compile(r'^\s*[*#]*\s*(第[一二三四五六七八九十百零\d]+[章节部分篇].*)'),
    # 附件一、附录A、附表1
    re.compile(r'^\s*[*#]*\s*(附[件录表][一二三四五六七八九十\dA-Za-z]+.*)'),
]
# 兼容旧代码引用
CHAPTER_PATTERNS = MAJOR_CHAPTER_PATTERNS


class ExtractorService:
    def __init__(self):
        self._docling_converter = None

    def _get_docling_converter(self):
        """懒加载 Docling Converter，减少启动时间并避免在非解析时占用资源"""
        if self._docling_converter is None:
            from docling.document_converter import DocumentConverter
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
            
            # 配置 Docling 的 PDF Pipeline 参数
            pipeline_options = PdfPipelineOptions()
            pipeline_options.do_table_structure = True
            pipeline_options.table_structure_options.mode = TableFormerMode.ACCURATE
            
            self._docling_converter = DocumentConverter(
                allowed_formats=[InputFormat.PDF, InputFormat.DOCX]
            )
        return self._docling_converter

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
                    
            # 前 N 页平均文本少于 50 字且含有图片，判定为扫描件
            avg_text = total_text_len / check_count
            if avg_text < 50 and has_images:
                logger.warning(f"检测到文件可能为扫描件 (平均文本长度: {avg_text})")
                return True
                
            return False
        except Exception as e:
            logger.error(f"检测扫描件出错: {str(e)}")
            return False

    def parse_with_mineru(self, file_path: str) -> List[Document]:
        """
        使用 MinerU 核心服务提取标准 Markdown 文本，并进行大章归组与自适应切分。
        """
        from app.services.mineru_service import mineru_service
        logger.info(f"开始使用 MinerU 主解析引擎处理文档: {file_path}")
        
        result = mineru_service.parse_file(file_path=file_path)
        md_text = result.get("markdown_content", "")
        # md_file_path: mineru_service 落盘的原始无切割 Markdown 文件路径，供前端原文展示用
        md_file_path = result.get("md_file_path", "")
        
        if not md_text or not md_text.strip():
            raise RuntimeError("MinerU 在线 API 解析返回的 Markdown 文本为空")

        chapters = self._group_markdown_text_by_chapter(md_text)
        
        final_docs: List[Document] = []
        chunk_index = 0
        for chapter in chapters:
            sub_docs = self._adaptive_split_chapter(chapter, start_index=chunk_index)
            for doc in sub_docs:
                doc.metadata["source"] = file_path
                # 将 output.md 路径注入每个 Chunk 的 metadata，
                # 供下游 parser_worker 存入 Document.parsed_metadata 后供前端读取
                doc.metadata["md_file_path"] = md_file_path
            final_docs.extend(sub_docs)
            chunk_index += len(sub_docs)
            
        logger.info(f"MinerU 主引擎解析切分完成: {len(chapters)} 个大章 → {len(final_docs)} 个 Chunk。")
        return final_docs

    def _group_markdown_text_by_chapter(self, markdown_text: str) -> List[Dict[str, Any]]:
        """
        将纯 Markdown 文本按 1 级大章 (第一章、第二章...) 进行全局归置与拼接。
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

    def convert_doc_to_docx(self, doc_path: str) -> str:
        """使用 LibreOffice 命令行将 .doc 强转为 .docx"""
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
        支持识别内嵌在 Docling Chunk 中间的标题行。
        """
        clean = line.replace('*', '').replace('#', '').strip()
        if not clean or len(clean) > 100:
            return None

        # 排除目录项 (以页码数字结尾)
        if re.search(r'\d+\s*$', clean):
            return None

        # 排除交叉引用句 (如“具体要求详见第四章项目需求”)
        if re.search(r'(详见|参见|遵循|依据|见)\s*第[一二三四五六七八九十\d]+[章节]', clean):
            return None

        for pattern in MAJOR_CHAPTER_PATTERNS:
            match = pattern.search(clean)
            if match:
                return clean

        return None

    def _detect_major_chapter(self, text: str) -> Optional[str]:
        """兼容性包装：检测大章标题"""
        lines = text.split('\n')
        for line in lines:
            res = self._detect_major_chapter_in_line(line)
            if res:
                return res
        return None

    def _detect_chapter_title(self, text: str) -> Optional[str]:
        """兼容性包装：检测大章标题"""
        return self._detect_major_chapter(text)

    def _group_chunks_by_chapter(self, raw_chunks: list) -> List[Dict[str, Any]]:
        """
        将 Docling HierarchicalChunker 输出碎片按「大章」(第一章、第二章...) 进行全局逐行精准归置。
        - 采用逐行扫描 (Line-by-line scan)，精准识别位于 Chunk 内部中间位置的大章标题 (如位于第4行的 **第四章 项目需求**)。
        - 增加交叉引用过滤，防止文中内联引用误开启假大章。
        - 采用全局字典合并相同大章，解决由于误分割导致的同名大章重复出现问题。
        """
        grouped_chapters: Dict[str, Dict[str, Any]] = {}
        chapter_order: List[str] = []
        
        current_chapter: str = "无章节/正文"
        
        for chunk in raw_chunks:
            # 提取页码与元素类型
            page_no = 1
            if chunk.meta.doc_items and chunk.meta.doc_items[0].prov:
                page_no = chunk.meta.doc_items[0].prov[0].page_no

            element_label = chunk.meta.doc_items[0].label if chunk.meta.doc_items else "text"

            # 策略1: 检查 Docling 元数据 headings 数组中是否包含 1 级大章标题
            if chunk.meta.headings:
                for heading_text in chunk.meta.headings:
                    clean_h = heading_text.replace('*', '').replace('#', '').strip()
                    if clean_h and len(clean_h) < 100:
                        matched = self._detect_major_chapter_in_line(clean_h)
                        if matched:
                            current_chapter = matched
                            break


            # 逐行扫描文本行，精密判断大章分割边界
            lines = chunk.text.split('\n')
            for line in lines:
                line_str = line.strip()
                if not line_str:
                    continue

                line_chapter = self._detect_major_chapter_in_line(line_str)
                if line_chapter:
                    current_chapter = line_chapter

                # 全局按大章归置行数据
                if current_chapter not in grouped_chapters:
                    chapter_order.append(current_chapter)
                    grouped_chapters[current_chapter] = {
                        "title": current_chapter,
                        "text": line_str,
                        "page_start": page_no,
                        "content_type": "chapter_block",
                        "trace_info": {
                            "chapter": current_chapter,
                            "headings": [current_chapter],
                            "element_label": element_label
                        }
                    }
                else:
                    grouped_chapters[current_chapter]["text"] += "\n" + line_str

        # 整理输出列表
        result_chapters: List[Dict[str, Any]] = []
        for title in chapter_order:
            block = grouped_chapters[title]
            if block["text"].strip():
                result_chapters.append(block)

        logger.info(f"大章归组完成，全局聚合去重后共 {len(result_chapters)} 个完整大章:")
        for i, ch in enumerate(result_chapters):
            logger.info(f"  章[{i}]: {ch['title']} ({len(ch['text'])} 字)")

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
            # 识别 Markdown 表格行判定：包含 '|' 且以 '|' 开头和结尾
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
            # 短章节：直接保留纯净原文
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
            # 长章节：自适应语义分块
            logger.info(
                f"章节 [{chapter_title}] 文本长度 {len(chapter_text)} 字 > {MAX_CHUNK_SIZE}，"
                f"启动语义聚类及表格防割裂分块。"
            )
            # 基础文本切分器
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=MAX_CHUNK_SIZE,
                chunk_overlap=CHUNK_OVERLAP,
                separators=["\n## ", "\n\n", "\n", "。", "；", ".", " "],
                length_function=len,
            )

            # 第一步：按二级标题 (## ) 划分为多个逻辑段落 (H2 Section)
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

            # 遍历每一个 H2 Section
            for h2_sec in h2_sections:
                h2_sec_stripped = h2_sec.strip()
                if not h2_sec_stripped:
                    continue
                
                # 如果当前 section 加入当前块不超限，则直接合并
                if current_chunk_len + len(h2_sec_stripped) <= MAX_CHUNK_SIZE:
                    current_chunk_parts.append(h2_sec_stripped)
                    current_chunk_len += len(h2_sec_stripped)
                    continue
                
                # 若超限，且当前块已积累了有意义的内容(>300字)，则先刷出当前块
                if current_chunk_len > 300:
                    sub_texts.append("\n\n".join(current_chunk_parts))
                    current_chunk_parts = []
                    current_chunk_len = 0
                
                # 再次判断当前 section 能否作为一个整体塞入（可能当前块被清空，或容忍略微超限）
                if current_chunk_len + len(h2_sec_stripped) <= MAX_CHUNK_SIZE:
                    current_chunk_parts.append(h2_sec_stripped)
                    current_chunk_len += len(h2_sec_stripped)
                else:
                    # 二级段落仍过长，不得不拆分，但需在内部保护表格及其上下文
                    blocks = self._extract_text_and_table_blocks(h2_sec_stripped)
                    for b in blocks:
                        b_type = b["type"]
                        b_content = b["content"].strip()
                        if not b_content:
                            continue
                        
                        if b_type == "table":
                            # 表格尽量不单独剥离上下文，若前置文本很短（<300字），不强行切断，容忍超限
                            if current_chunk_len + len(b_content) > MAX_CHUNK_SIZE and current_chunk_len > 300:
                                sub_texts.append("\n\n".join(current_chunk_parts))
                                current_chunk_parts = []
                                current_chunk_len = 0
                            
                            current_chunk_parts.append(b_content)
                            current_chunk_len += len(b_content)
                        else:
                            # 纯文本使用切分器切分
                            splits = splitter.split_text(b_content)
                            for s in splits:
                                if current_chunk_len + len(s) > MAX_CHUNK_SIZE and current_chunk_len > 300:
                                    sub_texts.append("\n\n".join(current_chunk_parts))
                                    current_chunk_parts = [s]
                                    current_chunk_len = len(s)
                                else:
                                    current_chunk_parts.append(s)
                                    current_chunk_len += len(s)

            # 刷出最后的残留内容
            if current_chunk_parts:
                sub_texts.append("\n\n".join(current_chunk_parts))

            logger.info(f"  => 语义及表格整块保护切分产出 {len(sub_texts)} 个子块。")
            
            # 生成最终 Document 列表
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
        核心解析与切片入口（MinerU 第一优先级路线）：
        1. 检测系统运行环境与 Token，若 MinerU 可用，优先调用 MinerU 主引擎。
        2. 若 MinerU 未部署/配置或提取失败，自动回退到 Docling 备用引擎。
        3. 自适应再分块与分配全局递增 chunk_index。
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")

        # 1. 第一优先级：调用 MinerU 官方解析引擎
        from app.services.mineru_service import mineru_service
        status = mineru_service.check_availability()
        if status.get("is_installed"):
            logger.info("✅ 探测到 MinerU 官方解析引擎已就绪，正在使用 MinerU 处理文档...")
            return self.parse_with_mineru(file_path)

        # 2. 备用路线：老旧 .doc 格式转换为 .docx
        if file_path.lower().endswith(".doc"):
            file_path = self.convert_doc_to_docx(file_path)

        # 3. 备用路线：Docling 引擎解析
        logger.info(f"启动 Docling 备用引擎解析文档: {file_path}")
        try:
            converter = self._get_docling_converter()
            conversion_result = converter.convert(file_path)
            
            # 仅在 DEBUG 级别输出 Docling 原始解析结果
            if logger.isEnabledFor(logging.DEBUG):
                try:
                    debug_output_path = file_path + ".debug.md"
                    with open(debug_output_path, "w", encoding="utf-8") as f:
                        f.write(conversion_result.document.export_to_markdown())
                    logger.debug(f"Docling 原始解析结果已保存至: {debug_output_path}")
                except Exception as inner_e:
                    logger.warning(f"保存 Docling 调试文件失败: {inner_e}")
            
            # 3. HierarchicalChunker 获取带结构元数据的碎片
            from docling_core.transforms.chunker.hierarchical_chunker import HierarchicalChunker
            
            chunker = HierarchicalChunker()
            raw_chunks = list(chunker.chunk(conversion_result.document))
            logger.info(f"HierarchicalChunker 初切完成，共 {len(raw_chunks)} 个碎片。")
            
            # 4. 按章节标题归组
            chapters = self._group_chunks_by_chapter(raw_chunks)
            
            # 5. 超长章节自适应再分块 + 分配全局递增 chunk_index
            final_docs: List[Document] = []
            chunk_index = 0
            
            for chapter in chapters:
                sub_docs = self._adaptive_split_chapter(chapter, start_index=chunk_index)
                # 填充 source 路径
                for doc in sub_docs:
                    doc.metadata["source"] = file_path
                final_docs.extend(sub_docs)
                chunk_index += len(sub_docs)
            
            logger.info(
                f"文档切分完成: {len(chapters)} 个章节 → {len(final_docs)} 个最终 Chunk "
                f"(MAX_CHUNK_SIZE={MAX_CHUNK_SIZE}, CHUNK_OVERLAP={CHUNK_OVERLAP})"
            )
            
            return final_docs
            
        except Exception as e:
            logger.error(f"Docling 解析失败: {str(e)}")
            raise e

# 单例导出
extractor_service = ExtractorService()
