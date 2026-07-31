import os
import re
import logging
from typing import List, Dict, Any, Optional
from langchain_core.documents import Document
try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

logger = logging.getLogger(__name__)

# ========== 切分策略常量 ==========
MAX_CHUNK_SIZE: int = 1200
CHUNK_OVERLAP: int = 200

MAJOR_CHAPTER_PATTERNS: List[re.Pattern] = [
    re.compile(r'^\s*[*#]*\s*(第[一二三四五六七八九十百零\d]+[章部分篇]\s*.*)'),
    re.compile(r'^\s*[*#]*\s*(附[件录表][一二三四五六七八九十\dA-Za-z]+.*)'),
]

# 招投标核心大章及关键考核一级根表单词典 (只认准顶级考核母单与回函，彻底屏蔽任意含有‘技术’、‘资质’、‘施工’的普通内嵌小节)
CORE_ROOT_BID_MODULES = r'(?:投标函|报价[函表]|开标一览表|偏离表|分项报价|报价清单|商务条款响应|技术[要求规范]*响应|技术架构|商务响应|法定代表人身份|授权委托书|业绩一览表|售后服务[承诺及]*[条方案]*|基本情况[介绍表]*|实施方案|施工方案|资格审查|服务响应)'
CORE_TABLE_SUFFIXES = r'(?:一览表|偏离表|配置表|报价表|汇总表|分析表|承诺[函书]|授权[函书]|证明文件|清单|清单明细)'

BID_CHAPTER_PATTERNS: List[re.Pattern] = [
    # 1. 明确的“第X章/第X部分/第X篇”等正规一级总纲（严厉去除“第X节”，因其必定是正文二级/三级子条款）
    re.compile(r'^\s*[*#]*\s*(第[一二三四五六七八九十百零\d]+[章部分篇]\s*.*)'),
    # 2. 明确的“附件X / 附表X / 附图X / 附录X”
    re.compile(r'^\s*[*#]*\s*((?:附[件录表]|附图)[一二三四五六七八九十\dA-Za-z]+.*)'),
    # 3. 含有关键核心模块名的汉字大写序号“一、/二、/三、...”
    re.compile(r'^\s*[*#]*\s*([一二三四五六七八九十百零]+、[^。，！？；\n]*?' + CORE_ROOT_BID_MODULES + r'[^。，！？；\n]*)$'),
    # 4. 特殊打分审核台账与凭条表头 (如 "2023 年以来类似项目业绩一览表", "开标一览表")
    re.compile(r'^\s*[*#]*\s*([^。，！？；\n]{3,35}' + CORE_TABLE_SUFFIXES + r')\s*[*#]*\s*$'),
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
        if not file_path.lower().endswith(".pdf") or fitz is None:
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

    def _clean_toc_title(self, text: str) -> str:
        """清理目录与标题中的引导线、页码、Markdown 符号等干扰字符"""
        clean = text.lstrip("#*-. ").strip()
        # 移除末端引导点与页码，例如 ".... 12", "--- 105", ". . . 4"
        clean = re.sub(r'[\s.·…\-_]+\d*\s*$', '', clean).strip()
        clean = clean.rstrip("。，；,;")
        return clean

    def _normalize_title_for_matching(self, text: str) -> str:
        """归一化标题名称用于匹配，剔除标点、多余空白及常用编号前缀"""
        s = self._clean_toc_title(text)
        s = re.sub(r'^[#*\s]+', '', s)
        # 去除首部常见序号：如 "1. ", "1.1 ", "第一章 ", "一、", "（一）"
        s = re.sub(r'^(?:第[一二三四五六七八九十百零\d]+[章部分篇节]|附[件录表图][一二三四五六七八九十\dA-Za-z]*|[一二三四五六七八九十]+[、.]|\(?[\d一二三四五六七八九十]+\)?[\s.、]|\d+(?:\.\d+)*[\s.、])', '', s).strip()
        return s

    def _extract_toc_chapters(self, markdown_text: str, doc_type: str = "general") -> List[str]:
        """
        全量提取 Markdown 中【目录】(TOC) 区域的所有章节标题白名单。
        全面兼容汉字序号（一、二、三）、数字序号（1.、1.1）、第X章、附件X等所有格式。
        """
        toc_chapters: List[str] = []
        lines = markdown_text.splitlines()
        in_toc = False
        empty_line_count = 0

        for line in lines:
            stripped = line.strip()
            if not stripped:
                if in_toc:
                    empty_line_count += 1
                    if empty_line_count > 12:
                        break
                continue
            empty_line_count = 0

            # 探测目录起始标记
            if not in_toc:
                clean_heading = stripped.replace('#', '').replace(' ', '').replace('　', '')
                if clean_heading in ["目录", "目录TOC", "CONTENTS", "目次", "目录概览"]:
                    in_toc = True
                continue

            clean_line = stripped.lstrip('#*-. ').strip()
            if not clean_line or len(clean_line) > 100:
                continue

            # 遇到无引导符号且在已有白名单中的完整标题时，视为目录结束进入正文
            if not re.search(r'[\d\.\-·…]{2,}', stripped) and any(clean_line == c for c in toc_chapters):
                break

            title_candidate = self._clean_toc_title(clean_line)
            if not title_candidate or len(title_candidate) > 70:
                continue

            # 过滤陈述句与非标题行
            if re.search(r'[，。！？；,;!?]', title_candidate):
                continue
            if re.search(r'(详见|参见|遵循|依据|见)\s*第', title_candidate):
                continue

            if title_candidate not in toc_chapters:
                toc_chapters.append(title_candidate)

            if len(toc_chapters) > 200:
                break

        if toc_chapters:
            logger.info(f"📑 目录提取成功！捕获 {len(toc_chapters)} 个目录结构字段: {toc_chapters[:5]}...")
        return toc_chapters

    def _detect_major_chapter_in_line(
        self,
        line: str,
        doc_type: str = "general",
        toc_chapters: Optional[List[str]] = None,
    ) -> Optional[str]:
        """
        判断单行文本是否为章节标题或目录字段。
        优先匹配 TOC 目录白名单，并支持 一、二、三 / 第X章 / Markdown # / ## 自动判定。
        """
        raw_strip = line.strip()
        if not raw_strip:
            return None

        clean = raw_strip.replace('*', '').replace('#', '').strip()
        if not clean or len(clean) > 70:
            return None

        # 排除包含句号问号问答的长段描述、结尾页码标点、引用陈述
        if re.search(r'[，。！？；,;!?]', clean):
            return None
        if re.search(r'\d+\s*$', clean) or re.search(r'[\.·…\-_]{2,}', clean):
            return None
        if re.search(r'(详见|参见|遵循|依据|见)\s*第[一二三四五六七八九十\d]+[章部分篇]', clean):
            return None

        # 1. 优先校验 TOC 目录白名单 (支持归一化全等与前后缀包含)
        if toc_chapters:
            clean_norm = self._normalize_title_for_matching(clean)
            for tc in toc_chapters:
                tc_norm = self._normalize_title_for_matching(tc)
                if clean == tc or (clean_norm and clean_norm == tc_norm):
                    return clean
                if len(clean) >= 4 and len(tc) >= 4:
                    if clean.startswith(tc) or tc.startswith(clean):
                        return clean

        # 2. 匹配标书与常规章节正则 (一、二、三 / 第X章 / 附件X / Markdown # / ##)
        patterns = BID_CHAPTER_PATTERNS if doc_type == "bid" else MAJOR_CHAPTER_PATTERNS
        for pattern in patterns:
            if pattern.search(raw_strip) or pattern.search(clean):
                return clean

        return None

    def _find_page_for_text(self, text_snippet: str, page_texts: Dict[int, str], current_page: int) -> int:
        """根据 PyMuPDF 页码索引文本，精准判断当前文本段落所在的物理页码"""
        if not text_snippet or not page_texts:
            return current_page
        
        clean_snippet = text_snippet.strip().replace('*', '').replace('#', '').replace('\n', '').replace(' ', '')[:25]
        if not clean_snippet or len(clean_snippet) < 3:
            return current_page
            
        max_page = max(page_texts.keys())
        for p in range(current_page, max_page + 1):
            p_txt = page_texts.get(p, "").replace('\n', '').replace(' ', '')
            if clean_snippet in p_txt:
                return p

        for p in range(1, current_page):
            p_txt = page_texts.get(p, "").replace('\n', '').replace(' ', '')
            if clean_snippet in p_txt:
                return p

        return current_page

    def _group_markdown_text_by_chapter(self, markdown_text: str, doc_type: str = "general", pdf_path: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        将纯 Markdown 文本按大章或独立表格层级进行全局归置与拼接。
        结合 PyMuPDF 物理页码映射引擎，为每一个章节块精准注入物理页码 (page_start)。
        """
        page_texts: Dict[int, str] = {}
        if pdf_path and os.path.exists(pdf_path) and pdf_path.lower().endswith(".pdf") and fitz:
            try:
                doc_fitz = fitz.open(pdf_path)
                for idx, page in enumerate(doc_fitz):
                    page_texts[idx + 1] = page.get_text()
                doc_fitz.close()
                logger.info(f"📄 已成功建立 PyMuPDF 全文 {len(page_texts)} 页物理定位索引")
            except Exception as e:
                logger.warning(f"无法读取 PDF 物理页码索引: {e}")

        toc_chapters = self._extract_toc_chapters(markdown_text, doc_type=doc_type)
        grouped_chapters: Dict[str, Dict[str, Any]] = {}
        chapter_order: List[str] = []
        current_chapter: str = "无章节/正文"
        current_page: int = 1

        lines = markdown_text.split('\n')
        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue

            if page_texts:
                current_page = self._find_page_for_text(line_str, page_texts, current_page)

            line_chap = self._detect_major_chapter_in_line(line_str, doc_type=doc_type, toc_chapters=toc_chapters)
            if line_chap:
                current_chapter = line_chap

            if current_chapter not in grouped_chapters:
                chapter_order.append(current_chapter)
                grouped_chapters[current_chapter] = {
                    "title": current_chapter,
                    "text": line_str,
                    "page_start": current_page,
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
    def _extract_text_and_table_blocks(self, text: str) -> List[Dict[str, Any]]:
        """
        将章节文本精准拆解为【普通文本段落块】与【完整的表格原子块】（兼容 Markdown 与 HTML 表格）。
        表格块将拥有独立存放特权，不与段落杂糅成同一 Chunk。
        """
        lines = text.splitlines()
        blocks: List[Dict[str, Any]] = []
        
        current_text_lines: List[str] = []
        current_table_lines: List[str] = []
        in_table = False
        in_html_table = False

        for line in lines:
            stripped = line.strip()
            lower_s = stripped.lower()

            if "<table" in lower_s:
                in_html_table = True
            
            is_md_table = (
                stripped.startswith("|") and 
                (stripped.endswith("|") or "|" in stripped[1:]) and
                len(stripped) > 2
            )
            is_html_table = in_html_table or any(lower_s.startswith(tag) for tag in ["<tr", "<td", "</tr", "</td", "</table"])

            is_table = is_md_table or is_html_table

            if is_table:
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

            if "</table>" in lower_s:
                in_html_table = False

        if current_table_lines:
            blocks.append({"type": "table", "content": "\n".join(current_table_lines)})
        if current_text_lines:
            blocks.append({"type": "text", "content": "\n".join(current_text_lines)})

        return blocks

    def _split_table_preserving_headers(self, table_text: str, max_size: int) -> List[str]:
        """
        对大型 Markdown 或 HTML 表格进行长文拆分，并在每个分块头部自动拼接原本的表头说明栏。
        彻底解决长表格跨段分开后字段属性定义丢失、大模型看图表产生幻觉的缺点。
        """
        lines = table_text.splitlines()
        if len(lines) <= 3 or len(table_text) <= max_size:
            return [table_text]
        
        header_lines: List[str] = []
        data_lines: List[str] = []
        
        if len(lines) >= 2 and lines[0].strip().startswith("|") and "-" in lines[1] and lines[1].strip().startswith("|"):
            header_lines = [lines[0], lines[1]]
            data_lines = lines[2:]
        elif len(lines) >= 1 and lines[0].strip().startswith("|"):
            header_lines = [lines[0]]
            data_lines = lines[1:]
        elif "<table" in lines[0].lower() or "<tr>" in lines[0].lower():
            header_lines = lines[:2]
            data_lines = lines[2:]
        else:
            return [table_text]
            
        header_text = "\n".join(header_lines)
        chunks: List[str] = []
        current_lines: List[str] = []
        current_len: int = len(header_text)
        
        for line in data_lines:
            line_len = len(line) + 1
            if current_len + line_len > max_size and current_lines:
                chunk_str = header_text + "\n" + "\n".join(current_lines) if header_text else "\n".join(current_lines)
                chunks.append(chunk_str.strip())
                current_lines = [line]
                current_len = len(header_text) + line_len
            else:
                current_lines.append(line)
                current_len += line_len
                
        if current_lines:
            chunk_str = header_text + "\n" + "\n".join(current_lines) if header_text else "\n".join(current_lines)
            chunks.append(chunk_str.strip())
            
        return chunks if chunks else [table_text]

    def _check_has_table(self, text: str) -> bool:
        if not text:
            return False
        lower_t = text.lower()
        if "<table" in lower_t or "</table>" in lower_t or "<tr>" in lower_t or "<td>" in lower_t:
            return True
        if "|" in text:
            return True
        return False

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
            has_tbl = self._check_has_table(chapter_text)
            docs.append(Document(
                page_content=chapter_text,
                metadata={
                    "section_title": chapter_title,
                    "parent_chapter": chapter_title,
                    "chunk_level": "L3" if has_tbl else "L1",
                    "chunk_index": start_index,
                    "page_num": chapter["page_start"],
                    "content_type": "table" if has_tbl else chapter["content_type"],
                    "has_table": has_tbl,
                    "trace_info": {
                        **chapter["trace_info"],
                        "parent_chapter": chapter_title,
                        "chunk_level": "L3" if has_tbl else "L1",
                        "has_table": has_tbl
                    },
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
                            # 强行刷新此前积累的文本，确保表格 100% 独立单存一个 Chunk
                            if current_chunk_parts:
                                sub_texts.append("\n\n".join(current_chunk_parts))
                                current_chunk_parts = []
                                current_chunk_len = 0
                            
                            if len(b_content) > MAX_CHUNK_SIZE:
                                table_splits = self._split_table_preserving_headers(b_content, MAX_CHUNK_SIZE)
                                for t_split in table_splits:
                                    sub_texts.append(t_split)
                            else:
                                sub_texts.append(b_content)
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
                has_tbl = self._check_has_table(sub_text)
                chunk_lvl = "L3" if has_tbl else "L2"
                docs.append(Document(
                    page_content=sub_text,
                    metadata={
                        "section_title": chapter_title,
                        "parent_chapter": chapter_title,
                        "chunk_level": chunk_lvl,
                        "chunk_index": start_index + j,
                        "page_num": chapter["page_start"],
                        "content_type": "table" if has_tbl else chapter["content_type"],
                        "has_table": has_tbl,
                        "trace_info": {
                            **chapter["trace_info"],
                            "parent_chapter": chapter_title,
                            "chunk_level": chunk_lvl,
                            "has_table": has_tbl
                        },
                        "source": "",
                    }
                ))
        
        return docs

    def parse_and_chunk(self, file_path: str, doc_type: str = "general") -> List[Document]:
        """
        核心调度与切片入口：根据策略模式 (Strategy Pattern) 选择合适的 Parser，并根据 doc_type 执行对应的定制分块
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")

        file_name = os.path.basename(file_path)
        ext = os.path.splitext(file_name)[1].lower()

        # 1. 预处理 Word 格式
        if ext == ".doc":
            file_path = self.convert_doc_to_docx(file_path)
            ext = ".docx"

        parse_result = None
        
        # 2. 路由与深度容灾切换：优先使用 MinerU 主引擎，发生超时或报错时无缝热切 Docling 备用引擎
        if ext == ".docx":
            logger.info(f"✅ 路由到 DocxParser: {file_name}")
            parser = self._get_docx_parser()
            parse_result = parser.parse(file_path)
        else:
            mineru = self._get_mineru_parser()
            if mineru.check_availability().get("is_installed"):
                logger.info(f"✅ 路由到 MinerUParser (主引擎): {file_name}")
                try:
                    parse_result = mineru.parse(file_path)
                except Exception as e:
                    logger.warning(f"⚠️ MinerU 主引擎调用异常或轮询终极超时 ({str(e)})，自动激发灾备保险开关 —— 即时切换致 DoclingParser (备用极强引擎) 完成通览解析！")
                    parser = self._get_docling_parser()
                    parse_result = parser.parse(file_path)
            else:
                logger.info(f"⚠️ MinerU 未接联或不可用，立刻顺滑载入 DoclingParser (备用引擎): {file_name}")
                parser = self._get_docling_parser()
                parse_result = parser.parse(file_path)

        md_text = parse_result.get("markdown_content", "")
        md_file_path = parse_result.get("md_file_path", "")

        if not md_text or not md_text.strip():
            raise RuntimeError(f"解析器返回空文本: {file_name}")

        # 4. 执行大章或专题模块归组 (结合 PDF 物理页码定位引擎)
        chapters = self._group_markdown_text_by_chapter(md_text, doc_type=doc_type, pdf_path=file_path)
        
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
