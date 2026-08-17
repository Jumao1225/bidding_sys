import os
import re
import logging
from typing import List, Dict, Any, Optional, Tuple
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
        """
        将旧版 .doc 格式转换为新版 .docx 格式。
        支持多级降级与容错策略：
        1. 在系统 PATH 或 Windows 常见安装目录中查找 LibreOffice (soffice.exe) 进行命令行无头转换。
        2. 在 Windows 环境下降级使用 MS Word (win32com) COM 接口转换。
        3. 降级尝试使用第三方 doc2docx 转换库。
        若所有转换方案均无法正常工作，抛出包含明确归因说明的 RuntimeError。
        """
        import shutil
        import subprocess
        import sys

        docx_path = doc_path + "x"
        if os.path.exists(docx_path):
            return docx_path

        errors: List[str] = []

        # 1. 优先查找并尝试 LibreOffice (soffice) 转换
        soffice_bin = shutil.which("soffice")
        if not soffice_bin and sys.platform == "win32":
            # 在 Windows 常见默认安装路径中搜索 LibreOffice
            candidate_paths = [
                os.environ.get("SOFFICE_PATH", ""),
                r"C:\Program Files\LibreOffice\program\soffice.exe",
                r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
                r"D:\Program Files\LibreOffice\program\soffice.exe",
            ]
            for candidate in candidate_paths:
                if candidate and os.path.isfile(candidate):
                    soffice_bin = candidate
                    break

        if soffice_bin:
            try:
                logger.info(f"开始使用 LibreOffice ({soffice_bin}) 转换 .doc 到 .docx: {doc_path}")
                cmd = [
                    soffice_bin, "--headless", "--convert-to", "docx",
                    doc_path, "--outdir", os.path.dirname(doc_path)
                ]
                result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)
                if result.returncode == 0 and os.path.exists(docx_path):
                    logger.info(f"LibreOffice 转换成功: {docx_path}")
                    return docx_path
                else:
                    err_text = result.stderr.strip() if result.stderr else "未知终端错误"
                    logger.warning(f"LibreOffice 执行未返回预期文件 (Exit Code {result.returncode}): {err_text}")
                    errors.append(f"LibreOffice 转换失败: {err_text}")
            except Exception as e:
                logger.warning(f"LibreOffice 转换过程抛出异常: {str(e)}")
                errors.append(f"LibreOffice 异常: {str(e)}")
        else:
            logger.warning("未能在 PATH 或标准路径中找到 LibreOffice (soffice)，准备尝试备选方案")

        # 2. 在 Windows 环境下降级使用 MS Word (win32com) 转换
        if sys.platform == "win32":
            try:
                logger.info(f"尝试使用 MS Word (win32com) 降级转换 .doc 到 .docx: {doc_path}")
                import win32com.client
                import pythoncom

                pythoncom.CoInitialize()
                word = None
                try:
                    word = win32com.client.DispatchEx("Word.Application")
                    word.Visible = False
                    word.DisplayAlerts = False
                    abs_doc = os.path.abspath(doc_path)
                    abs_docx = os.path.abspath(docx_path)
                    doc = word.Documents.Open(abs_doc)
                    # FileFormat=16 对应 Word 的 wdFormatXMLDocument (.docx) 格式
                    doc.SaveAs2(abs_docx, FileFormat=16)
                    doc.Close()
                    if os.path.exists(docx_path):
                        logger.info(f"MS Word (win32com) 转换成功: {docx_path}")
                        return docx_path
                finally:
                    if word:
                        try:
                            word.Quit()
                        except Exception as quit_err:
                            logger.warning(f"关闭 MS Word COM 对象异常: {str(quit_err)}")
                    pythoncom.CoUninitialize()
            except Exception as e:
                logger.warning(f"MS Word (win32com) 转换过程抛出异常: {str(e)}")
                errors.append(f"MS Word (win32com) 异常: {str(e)}")

        # 3. 降级尝试使用 doc2docx 库
        try:
            import importlib
            doc2docx_mod = importlib.import_module("doc2docx")
            convert_func = getattr(doc2docx_mod, "convert", None)
            if convert_func:
                logger.info(f"尝试使用 doc2docx 库转换 .doc 到 .docx: {doc_path}")
                convert_func(doc_path, docx_path)
                if os.path.exists(docx_path):
                    logger.info(f"doc2docx 转换成功: {docx_path}")
                    return docx_path
        except (ImportError, ModuleNotFoundError):
            pass
        except Exception as e:
            logger.warning(f"doc2docx 转换抛出异常: {str(e)}")
            errors.append(f"doc2docx 异常: {str(e)}")

        # 4. 若全线方案均无法完成转换，抛出清晰异常说明
        detail_msg = "; ".join(errors) if errors else "系统未检测到 LibreOffice 或 MS Word 转换引擎"
        err_msg = (
            f".doc 转 .docx 失败：{detail_msg}。"
            f"建议：请在服务器/本地安装 LibreOffice 并将其添加至系统环境变量 PATH，或安装 Microsoft Word。"
        )
        logger.error(err_msg)
        raise RuntimeError(err_msg)

    def _clean_toc_title(self, text: str) -> str:
        """清理目录与标题中的引导线、页码、Markdown 符号等干扰字符"""
        clean = text.replace('\ufffd', '').replace('\ufeff', '').lstrip("#*-. ").strip()
        # 移除末端引导点与页码，例如 ".... 12", "--- 105", ". . . 4"
        clean = re.sub(r'[\s.·…\-_]+\d*\s*$', '', clean).strip()
        clean = clean.rstrip("。，；,;")
        return clean

    def _normalize_title_for_matching(self, text: str) -> str:
        """归一化标题名称用于匹配，剔除标点、多余空白及常用编号前缀"""
        s = self._clean_toc_title(text)
        s = re.sub(r'^[\ufffd\ufeff#*\s]+', '', s)
        # 去除首部常见序号：如 "1. ", "1.1 ", "第一章 ", "一、", "（一）"
        s = re.sub(r'^(?:第[一二三四五六七八九十百零\d]+[章部分篇节]|附[件录表图][一二三四五六七八九十\dA-Za-z]*|[一二三四五六七八九十]+[、.]|\(?[\d一二三四五六七八九十]+\)?[\s.、]|\d+(?:\.\d+)*[\s.、])', '', s).strip()
        return s

    def _extract_toc_chapters(self, markdown_text: str, doc_type: str = "general") -> Tuple[List[str], Dict[str, List[str]]]:
        """
        全量提取 Markdown 中【目录】(TOC) 区域的所有章节标题白名单，
        并按目录包含关系自动构建每个章节的完整父子层级映射 (toc_hierarchy_map)。
        """
        toc_chapters: List[str] = []
        toc_hierarchy_map: Dict[str, List[str]] = {}
        lines = markdown_text.splitlines()
        in_toc = False
        empty_line_count = 0
        toc_stack: List[str] = []

        TOC_KEYWORDS = ["目录", "目录TOC", "CONTENTS", "目次", "目录概览", "投标文件目录", "标书目录", "投标目录"]

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
                clean_heading = re.sub(r'[#\s　【】:：]', '', stripped)
                if clean_heading in TOC_KEYWORDS:
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

            # 过滤包含中途标点的陈述句，允许结尾句号
            clean_candidate = title_candidate.rstrip("。，；,;!?！？")
            if re.search(r'[，！？；,;!?]', clean_candidate):
                continue
            if re.search(r'(详见|参见|遵循|依据|见)\s*第', title_candidate):
                continue

            if title_candidate not in toc_chapters:
                toc_chapters.append(title_candidate)

                # 判定当前目录项的固有结构层级 lvl
                if re.match(r'^\s*([一二三四五六七八九十百]+[、.])', title_candidate):
                    lvl = 1
                elif re.match(r'^\s*(第[一二三四五六七八九十\d]+[章部分篇]|附[件录表图])', title_candidate):
                    lvl = 2
                elif re.match(r'^\s*(第[一二三四五六七八九十\d]+节)', title_candidate):
                    lvl = 3
                elif re.match(r'^\s*[\(（][一二三四五六七八九十\d]+[\)）]', title_candidate):
                    lvl = 4
                else:
                    # 对于无特定序号前缀的非标标题项（如 "投标人自有设施设备情况"）：
                    if len(toc_stack) == 1:
                        lvl = 2  # 挂在 L1 下作为 L2 同级/子级项
                    elif len(toc_stack) >= 2:
                        lvl = len(toc_stack)  # 保持当前深度，平级替换末位项
                    else:
                        lvl = 1

                # 根据 lvl 维护目录堆栈 toc_stack
                if lvl == 1:
                    toc_stack = [title_candidate]
                elif lvl == 2:
                    toc_stack = [toc_stack[0], title_candidate] if toc_stack else [title_candidate]
                elif lvl == 3:
                    if len(toc_stack) >= 2:
                        toc_stack = [toc_stack[0], toc_stack[1], title_candidate]
                    elif len(toc_stack) == 1:
                        toc_stack = [toc_stack[0], title_candidate]
                    else:
                        toc_stack = [title_candidate]
                elif lvl == 4:
                    if len(toc_stack) >= 3:
                        toc_stack = [toc_stack[0], toc_stack[1], toc_stack[2], title_candidate]
                    elif len(toc_stack) >= 1:
                        toc_stack = list(toc_stack[:3]) + [title_candidate]
                    else:
                        toc_stack = [title_candidate]

                # 保存映射，包括原名、去除结尾标点的版本和归一化名称（强制最深只挂到 2 层树干，如 "七、设计方案、服务方案 > 第六章 培训方案"）
                capped_stack = toc_stack[:2]
                toc_hierarchy_map[title_candidate] = list(capped_stack)
                if clean_candidate and clean_candidate != title_candidate:
                    toc_hierarchy_map[clean_candidate] = list(capped_stack)
                norm_title = self._normalize_title_for_matching(title_candidate)
                if norm_title:
                    toc_hierarchy_map[norm_title] = list(capped_stack)

            if len(toc_chapters) > 200:
                break

        if toc_chapters:
            formatted_toc = "\n".join([f"  {idx+1:02d}. {chap} -> {' > '.join(toc_hierarchy_map.get(chap, [chap]))}" for idx, chap in enumerate(toc_chapters)])
            logger.info(f"📑 目录提取成功！共捕获 {len(toc_chapters)} 个目录结构大纲字段:\n{formatted_toc}")
        return toc_chapters, toc_hierarchy_map

    def _detect_heading_level(
        self,
        line: str,
        doc_type: str = "general",
        toc_chapters: Optional[List[str]] = None,
        stack: Optional[List[str]] = None,
    ) -> Optional[tuple[int, str]]:
        """
        探测单行文本的标题层级 (Level 1, 2, 3) 与清洗后的标题字符串。
        L1: 根大项 (如 一、投标函格式, 八、设计方案、施工方案, 十三、其他材料)
        L2: 大章 (如 第一章 设计方案, 第二章 施工方案, 附件一)
        L3: 子节 (如 第一节 项目可行性评估分析)
        """
        raw_strip = line.strip()
        if not raw_strip:
            return None

        clean = raw_strip.replace('*', '').replace('#', '').strip()
        if not clean or len(clean) > 70:
            return None

        # 排除“目录/CONTENTS/目次”关键字，防止审计报告等附件内部的“目录”行重置顶级堆栈
        if clean in ["目录", "目录TOC", "CONTENTS", "目次", "目录概览", "投标文件目录", "标书目录", "投标目录"]:
            return None

        # 排除包含标点长段描述、结尾引导点符、引用陈述
        if re.search(r'[，。！？；,;!?]', clean):
            return None
        if re.search(r'[\.·…\-_]{2,}', raw_strip):
            return None
        if re.search(r'(详见|参见|遵循|依据|见)\s*第[一二三四五六七八九十\d]+[章部分篇节]', clean):
            return None

        # ========== 模式 A: 招标文件 (doc_type == "general") 严格仅抓取一级顶级大章 ==========
        if doc_type == "general":
            # 剥离 Markdown (#, * 等) 与 HTML 标签 (如 <u>/</u>)
            clean_title = re.sub(r'<[^>]+>', '', raw_strip)
            clean_title = re.sub(r'[*#_`~]', '', clean_title).strip()
            # 严格匹配一级大章 (如：第一章 招标公告、第二部分 投标人须知、附件一 格式等)
            m_general = re.match(r'^\s*(第[一二三四五六七八九十百零\d]+[章部分篇]\s*.*|附[件录表图][一二三四五六七八九十\dA-Za-z]+.*)$', clean_title)
            if m_general:
                canonical_chap = m_general.group(1).strip()
                canonical_chap = re.sub(r'\s+', ' ', canonical_chap)
                return (1, canonical_chap)
            return None

        # 1. 校验 TOC 目录白名单 (最高权威：只要匹配目录白名单中的项，统统按 TOC 标准层级与规范名称精确对齐返回)
        if doc_type != "general" and toc_chapters:
            clean_norm = self._normalize_title_for_matching(clean)
            for tc in toc_chapters:
                tc_norm = self._normalize_title_for_matching(tc)
                if clean == tc or (clean_norm and clean_norm == tc_norm):
                    canonical_title = tc
                    if re.match(r'^[一二三四五六七八九十]+[、.]', tc):
                        return (1, canonical_title)
                    elif re.match(r'^第[一二三四五六七八九十\d]+[章部分篇]', tc) or re.match(r'^附[件录表图]', tc):
                        return (2, canonical_title)
                    else:
                        return (3, canonical_title)

        # 2. L1: 汉字序号顶级大项 (如 一、投标函格式 ... 三、资格证明文件 ... 十三、其他材料)
        # 无论 PDF 解析引擎输出几个 #，只要是“一~十三、”标准大项或核心模块，统统优先提升为 Level 1 根节点
        l1_match = re.match(r'^\s*[*#]*\s*([一二三四五六七八九十百]+[、.][^。，！？；\n]*)$', raw_strip)
        if l1_match:
            title = l1_match.group(1).strip()
            title_norm = self._normalize_title_for_matching(title)
            in_main_toc = bool(toc_chapters and any(title_norm == self._normalize_title_for_matching(tc) for tc in toc_chapters))
            
            # 如果当前 stack[0] 是目录中的合法顶级根大项（如 三、资格证明文件），且新出现的序号标题不在主目录中（如附件内部的 "一、审计意见"），
            # 绝对禁止其重置根节点，统统下沉为 L3 子节点，确保所有资质附件 100% 包裹在所属大章树下！
            stack_root_in_toc = bool(stack and toc_chapters and any(self._normalize_title_for_matching(stack[0]) == self._normalize_title_for_matching(tc) for tc in toc_chapters))
            if stack_root_in_toc and not in_main_toc:
                return (3, title)

            is_std_num = bool(re.match(r'^[一二三四五六七八九十]+\s*[、.]', title))
            is_root_module = bool(re.search(CORE_ROOT_BID_MODULES, title)) or any(kw in title for kw in ['投标', '报价', '资格', '方案', '偏离', '介绍', '材料', '声明', '承诺', '文件', '对照表', '响应'])
            is_non_toc_cert = any(kw in title for kw in ['证书', '证明', '合同', '身份证', '执照', '报告']) if not is_std_num else False
            if not is_non_toc_cert and (not stack or is_root_module or is_std_num or in_main_toc):
                return (1, title)
            else:
                return (3, title)

        # 3. 原生 Markdown 标记（处理一般 Heading）
        if raw_strip.startswith('# '):
            title_norm = self._normalize_title_for_matching(clean)
            in_main_toc = bool(toc_chapters and any(title_norm == self._normalize_title_for_matching(tc) for tc in toc_chapters))
            
            # 关键拦截：如果一个 # 单井号标题包含 证书/证明/合同/身份证/执照/报告 且不在 TOC 目录白名单中，
            # 绝对禁止其升级为 Level 1 根节点霸占 stack[0]！
            is_non_toc_cert = any(kw in clean for kw in ['证书', '证明', '合同', '身份证', '执照', '报告']) if not in_main_toc else False
            if is_non_toc_cert:
                return (2, clean)

            stack_root_in_toc = bool(stack and toc_chapters and any(self._normalize_title_for_matching(stack[0]) == self._normalize_title_for_matching(tc) for tc in toc_chapters))
            if stack_root_in_toc and not in_main_toc:
                return (2, clean)
            return (1, clean)
        elif raw_strip.startswith('## '):
            return (2, clean)
        elif raw_strip.startswith('### '):
            return (3, clean)

        # 4. L2: 第一章/附件X
        l2_match = re.match(r'^\s*[*#]*\s*(第[一二三四五六七八九十百零\d]+[章部分篇]\s*.*|附[件录表图][一二三四五六七八九十\dA-Za-z]+.*)$', raw_strip)
        if l2_match:
            return (2, l2_match.group(1).strip())

        # 5. L3: 第一节
        l3_match = re.match(r'^\s*[*#]*\s*(第[一二三四五六七八九十百零\d]+节\s*.*)$', raw_strip)
        if l3_match:
            return (3, l3_match.group(1).strip())

        # 6. 降级到常规判定（仅当文本包含于 TOC 或堆栈为空时允许升为 L1，防止非 TOC 证书标题霸占 L1 根节点）
        line_chap = self._detect_major_chapter_in_line(line, doc_type=doc_type, toc_chapters=toc_chapters)
        if line_chap:
            is_cert_or_contract = any(kw in line_chap for kw in ['证书', '证明', '合同', '身份证', '执照', '报告'])
            in_toc = bool(not toc_chapters or any(self._normalize_title_for_matching(line_chap) == self._normalize_title_for_matching(tc) for tc in toc_chapters))
            if not is_cert_or_contract and (in_toc or not stack):
                return (1, line_chap)
            else:
                return (3, line_chap)

        return None

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

        # 1. 只有当 doc_type != "general" (如投标文件 "bid") 时才校验 TOC 目录白名单；
        if doc_type != "general" and toc_chapters:
            clean_norm = self._normalize_title_for_matching(clean)
            for tc in toc_chapters:
                tc_norm = self._normalize_title_for_matching(tc)
                if clean == tc or (clean_norm and clean_norm == tc_norm):
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
        结合 TOC 目录页隔离算法与动态层级栈 (section_stack)，确保每个正文段落与表格都获得完整的 section_path。
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

        # 仅在处理投标文件 (doc_type == "bid") 时提取 TOC 目录白名单与结构树映射；
        if doc_type == "bid":
            toc_chapters, toc_hierarchy_map = self._extract_toc_chapters(markdown_text, doc_type=doc_type)
        else:
            toc_chapters, toc_hierarchy_map = [], {}

        result_chapters: List[Dict[str, Any]] = []
        current_block: Optional[Dict[str, Any]] = None
        stack: List[str] = []
        current_page: int = 1
        in_toc = False
        toc_passed = False
        TOC_KEYWORDS = ["目录", "目录TOC", "CONTENTS", "目次", "目录概览", "投标文件目录", "标书目录", "投标目录"]

        lines = markdown_text.split('\n')
        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue

            if page_texts:
                current_page = self._find_page_for_text(line_str, page_texts, current_page)

            # 探测/处理目录页 (TOC Page Isolation)
            clean_heading = re.sub(r'[#\s　【】:：]', '', line_str)
            if doc_type == "bid" and not toc_passed and clean_heading in TOC_KEYWORDS:
                in_toc = True
                if current_block and current_block["text"].strip():
                    result_chapters.append(current_block)
                current_block = {
                    "title": "目录",
                    "section_path": "目录",
                    "text": line_str,
                    "page_start": current_page,
                    "content_type": "toc_block",
                    "trace_info": {"chapter": "目录", "section_path": "目录", "hierarchy": ["目录"]}
                }
                continue

            if in_toc:
                # 检查目录页是否结束（当行无引导点符，且匹配 TOC 白名单或正文标准标题正则）
                is_dots = bool(re.search(r'[\d\.\-·…]{2,}', line_str))
                clean_norm = self._normalize_title_for_matching(line_str)
                is_toc_match = bool(toc_chapters and any(clean_norm == self._normalize_title_for_matching(tc) for tc in toc_chapters))
                is_body_h1 = bool(re.match(r'^\s*[*#]*\s*(?:[一二三四五六七八九十百]+[、.]|第[一二三四五六七八九十\d]+[章部分篇]|附[件录表图])', line_str))
                if not is_dots and (is_toc_match or is_body_h1):
                    in_toc = False
                    toc_passed = True
                    if current_block and current_block["text"].strip():
                        result_chapters.append(current_block)
                        current_block = None
                else:
                    if current_block:
                        current_block["text"] += "\n" + line_str
                    continue

            # 探测正文标题层级
            # 1. 优先校验 TOC 目录白名单与结构树映射 (最高权威)
            matched_toc_chain = None
            if doc_type == "bid" and toc_hierarchy_map:
                clean_line = line_str.lstrip('#*-. ').strip()
                clean_norm = self._normalize_title_for_matching(clean_line)
                if clean_line in toc_hierarchy_map:
                    matched_toc_chain = toc_hierarchy_map[clean_line]
                elif clean_norm in toc_hierarchy_map:
                    matched_toc_chain = toc_hierarchy_map[clean_norm]

            if matched_toc_chain:
                stack = list(matched_toc_chain[:2])
                title = stack[-1]
                section_path = " > ".join(stack)

                if current_block and current_block["text"].strip():
                    block_body = "\n".join([l for l in current_block["text"].split('\n') if l.strip() and not l.strip().startswith('#')])
                    if len(block_body.strip()) > 5 or current_block.get("content_type") == "toc_block":
                        result_chapters.append(current_block)

                current_block = {
                    "title": title,
                    "section_path": section_path,
                    "text": line_str,
                    "page_start": current_page,
                    "content_type": "chapter_block",
                    "trace_info": {
                        "chapter": title,
                        "section_path": section_path,
                        "hierarchy": list(stack),
                        "depth": len(stack),
                        "level": f"L{len(stack)}" if stack else "L0"
                    }
                }
            else:
                heading_res = self._detect_heading_level(line_str, doc_type=doc_type, toc_chapters=toc_chapters, stack=stack)
                if heading_res:
                    level, title = heading_res
                    
                    # 保护 TOC 树干节点：非 TOC 目录中的局部子标题（如 (一)、### 细节小节）绝对不能打破父级 TOC 树干，且限定层级最多两层！
                    if doc_type == "bid" and toc_chapters and stack:
                        stack = stack[:2]
                    else:
                        if level == 1:
                            stack = [title]
                        elif level >= 2:
                            stack = [stack[0], title] if stack else [title]
                        stack = stack[:2]

                    section_path = " > ".join(stack)

                    if current_block and current_block["text"].strip():
                        block_body = "\n".join([l for l in current_block["text"].split('\n') if l.strip() and not l.strip().startswith('#')])
                        if len(block_body.strip()) > 5 or current_block.get("content_type") == "toc_block":
                            result_chapters.append(current_block)

                    current_block = {
                        "title": title,
                        "section_path": section_path,
                        "text": line_str,
                        "page_start": current_page,
                        "content_type": "chapter_block",
                        "trace_info": {
                            "chapter": title,
                            "section_path": section_path,
                            "hierarchy": list(stack),
                            "depth": len(stack),
                            "level": f"L{len(stack)}" if stack else "L0"
                        }
                    }
                else:
                    if not current_block:
                        section_path = " > ".join(stack) if stack else "正文/未分类"
                        current_block = {
                            "title": stack[-1] if stack else "无章节/正文",
                            "section_path": section_path,
                            "text": line_str,
                            "page_start": current_page,
                            "content_type": "chapter_block",
                            "trace_info": {
                                "chapter": stack[-1] if stack else "无章节/正文",
                                "section_path": section_path,
                                "hierarchy": list(stack),
                                "depth": len(stack),
                                "level": f"L{len(stack)}" if stack else "L0"
                            }
                        }
                    else:
                        current_block["text"] += "\n" + line_str

        if current_block and current_block["text"].strip():
            result_chapters.append(current_block)

        return result_chapters

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

    def _adaptive_split_chapter(self, chapter: Dict[str, Any], start_index: int, doc_type: str = "general") -> List[Document]:
        """
        对单个大章进行自适应分块：
        - 若 doc_type == "general" (招标文件)：复刻上一版 (c307c34) 策略，保留完整的大章/段落结构，表格随文本平滑切割；
        - 若 doc_type == "bid" (投标文件)：维持最新的专属策略，表格 100% 独立成块，超长表格拼接原始表头说明并注入 chunk_level 溯源属性与 section_path 上下文。
        """
        from langchain_text_splitters import RecursiveCharacterTextSplitter
        
        docs: List[Document] = []
        chapter_text = chapter["text"].strip()
        
        if not chapter_text:
            return docs
        
        chapter_title = chapter["title"]
        section_path = chapter.get("section_path") or chapter_title
        parent_chapter = chapter_title
        if isinstance(chapter.get("trace_info"), dict) and chapter.get("trace_info").get("hierarchy"):
            parent_chapter = chapter["trace_info"]["hierarchy"][0]

        # ========== 模式 1: 招标文件 (doc_type == "general") 复刻上一版切块逻辑 ==========
        if doc_type == "general":
            if len(chapter_text) <= MAX_CHUNK_SIZE:
                docs.append(Document(
                    page_content=chapter_text,
                    metadata={
                        "section_title": chapter_title,
                        "section_path": section_path,
                        "chunk_index": start_index,
                        "page_num": chapter["page_start"],
                        "content_type": chapter["content_type"],
                        "trace_info": {**chapter["trace_info"], "section_path": section_path},
                        "source": "",
                    }
                ))
            else:
                logger.info(f"招标文件大章 [{chapter_title}] 文本长度 {len(chapter_text)} 字 > {MAX_CHUNK_SIZE}，启动上一版平滑拆分逻辑。")
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
                            "section_path": section_path,
                            "chunk_index": start_index + j,
                            "page_num": chapter["page_start"],
                            "content_type": chapter["content_type"],
                            "trace_info": {**chapter["trace_info"], "section_path": section_path},
                            "source": "",
                        }
                    ))
            return docs

        # ========== 模式 2: 投标文件 (doc_type == "bid") 维持精细化分块 + 结构上下文注入 ==========
        def _format_bid_content(raw_txt: str) -> str:
            if section_path and section_path != "目录" and not raw_txt.startswith("[所属章节:"):
                return f"[所属章节: {section_path}]\n\n{raw_txt}"
            return raw_txt

        if len(chapter_text) <= MAX_CHUNK_SIZE:
            has_tbl = self._check_has_table(chapter_text)
            content_formatted = _format_bid_content(chapter_text)
            docs.append(Document(
                page_content=content_formatted,
                metadata={
                    "section_title": section_path[:250],
                    "section_path": section_path,
                    "parent_chapter": parent_chapter,
                    "chunk_level": "L3" if has_tbl else "L1",
                    "chunk_index": start_index,
                    "page_num": chapter["page_start"],
                    "content_type": "table" if has_tbl else chapter["content_type"],
                    "has_table": has_tbl,
                    "trace_info": {
                        **chapter["trace_info"],
                        "section_path": section_path,
                        "parent_chapter": parent_chapter,
                        "chunk_level": "L3" if has_tbl else "L1",
                        "has_table": has_tbl
                    },
                    "source": "",
                }
            ))
        else:
            logger.info(
                f"投标文件章节 [{section_path}] 文本长度 {len(chapter_text)} 字 > {MAX_CHUNK_SIZE}，"
                f"启动表格隔离及表头自动补全拆分逻辑。"
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
                content_formatted = _format_bid_content(sub_text)
                docs.append(Document(
                    page_content=content_formatted,
                    metadata={
                        "section_title": section_path[:250],
                        "section_path": section_path,
                        "parent_chapter": parent_chapter,
                        "chunk_level": chunk_lvl,
                        "chunk_index": start_index + j,
                        "page_num": chapter["page_start"],
                        "content_type": "table" if has_tbl else chapter["content_type"],
                        "has_table": has_tbl,
                        "trace_info": {
                            **chapter["trace_info"],
                            "section_path": section_path,
                            "parent_chapter": parent_chapter,
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
                    parse_result = mineru.parse(file_path, max_retries=2)
                except Exception as e:
                    logger.warning(
                        f"⚠️ MinerU 主引擎在重试 2 次后依然异常 ({str(e)})，自动激发灾备保险开关 —— 即时切换至 DoclingParser (备用极强引擎) 完成通览解析！"
                    )
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
        logger.info(f"📋 成功提取到 {len(chapters)} 个顶级大章:")
        for idx, chap in enumerate(chapters, 1):
            logger.info(f"  [{idx:02d}] {chap['title']}")
        
        # 5. 自适应再分块与元数据注入
        final_docs: List[Document] = []
        chunk_index = 0
        for chapter in chapters:
            sub_docs = self._adaptive_split_chapter(chapter, start_index=chunk_index, doc_type=doc_type)
            for doc in sub_docs:
                doc.metadata["source"] = file_path
                doc.metadata["md_file_path"] = md_file_path
            final_docs.extend(sub_docs)
            chunk_index += len(sub_docs)
            
        logger.info(f"文档切分完成: {len(chapters)} 个大章 → {len(final_docs)} 个 Chunk。")
        return final_docs

# 单例导出
extractor_service = ExtractorService()
