"""
投标文件格式提取与切片服务 (Bid Format Extractor Service)

负责定位并提取招标文件中的“投标文件格式/组成”章节：
1. 原生 DOCX 模式：对原始 Word (.docx/.doc) 文件进行底层 DOM 结构切片，保留 100% 原始格式与表格，并统一修改文字为黑色。
2. LLM 结构化重建模式：针对 PDF 格式，通过 LLM 识别定位并结合 DocxExporterService 重建规范 Word。
"""

import os
import re
import io
import copy
import json
import zipfile
import uuid
from typing import Tuple, Optional, List, Dict, Any
from loguru import logger
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from pydantic import ValidationError
from docx import Document
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls
from docx.shared import RGBColor, Pt, Inches

from app.db.crud.document import document_crud
from app.services.extractor_service import ExtractorService
from app.services.docx_exporter_service import docx_exporter_service
from app.services.llm_service import LLMService, ModelUnavailableError
from app.schemas.bid_generator import (
    BidFormatStructure,
    BidFormatSection,
    ContentTypeEnum,
    BidFormatLocatorResult,
)


class BidFormatExtractorService:
    """
    投标文件格式提取与导出核心业务服务
    """

    # 结构选择器或大模型兜底策略发生变化时，旧缓存必须自动失效，避免继续返回历史错误切片。
    _DOCX_TEMPLATE_SELECTOR_VERSION = "dom-structure-v3-llm-fulltext"

    def __init__(self):
        self.extractor_service = ExtractorService()
        self.llm_service = LLMService()

        # 匹配“投标文件格式”大章标题正则表达式探照灯 (兼容 Markdown # / ** / ## 标记与内部空格)
        self.chapter_start_patterns = [
            re.compile(r'^[#\s\*]*第\s*[一二三四五六七八九十\d]+\s*[章篇部分卷节][\s\:\、\.\*]*(投标文件格式|应答文件格式|响应文件格式|投标文件组成|应答文件组成|格式及附件|投标文件格式要求|投标格式|响应格式)'),
            re.compile(r'^[#\s\*]*(投标文件格式|应答文件格式|响应文件格式|投标文件格式及附件|投标格式及要求)[\s\*]*$'),
            re.compile(r'^[#\s\*]*附\s*[件录][\s\:\、\.\*]*(投标文件格式|应答文件格式|响应文件格式|投标文件组成|投标格式)'),
        ]

        # 匹配下一个大章（用于判定“投标文件格式”章节的终止界限，兼容 Markdown # / ** 标记）
        self.chapter_next_patterns = [
            re.compile(r'^[#\s\*]*第\s*[一二三四五六七八九十\d]+\s*[章篇部分卷]'),
        ]

        # 章节正文特征仅用于区分目录与正文，不依赖固定章节编号或固定“三册”结构。
        self.format_body_markers = (
            "投标函",
            "应答函",
            "报价函",
            "授权委托",
            "法定代表人",
            "偏离表",
            "报价明细",
            "报价表",
            "承诺书",
            "资格审查",
            "商务响应",
            "技术响应",
            "格式附件",
        )

    def _get_bid_format_cache_paths(self, doc_id: str) -> Tuple[str, str]:
        """
        获取文档原格式模板缓存及其元数据文件路径。

        缓存使用文档 ID 隔离，避免不同文档之间复用错误的 Word 模板；元数据用于
        校验原始招标文件是否已经发生变化。
        """
        safe_doc_id = re.sub(r"[^A-Za-z0-9_-]", "_", str(doc_id or "")) or "unknown"
        cache_dir = os.path.join(os.getcwd(), "uploads", "bid_format_cache")
        return (
            os.path.join(cache_dir, f"{safe_doc_id}.docx"),
            os.path.join(cache_dir, f"{safe_doc_id}.json"),
        )

    @staticmethod
    def _build_source_fingerprint(file_path: str) -> Dict[str, Any]:
        """构建原始文件指纹，用于判断已缓存模板是否仍然有效。"""
        file_stat = os.stat(file_path)
        return {
            "file_path": os.path.abspath(file_path),
            "file_size": file_stat.st_size,
            "file_mtime_ns": file_stat.st_mtime_ns,
        }

    def _read_cached_bid_format_template(
        self,
        doc_id: str,
        source_file_path: str,
    ) -> Optional[Tuple[bytes, str]]:
        """
        读取此前已经提取的原格式模板。

        缓存只在原始文件路径、大小和修改时间都一致时命中；外部绑定模板不写入该
        缓存，因此调用方可以在本方法前优先处理外部模板。
        """
        cache_path, metadata_path = self._get_bid_format_cache_paths(doc_id)
        if not os.path.isfile(cache_path) or not os.path.isfile(metadata_path):
            return None

        try:
            with open(metadata_path, "r", encoding="utf-8") as metadata_file:
                metadata = json.load(metadata_file)
            expected_fingerprint = self._build_source_fingerprint(source_file_path)
            if metadata.get("source_fingerprint") != expected_fingerprint:
                logger.info("原格式模板缓存已过期，准备重新提取: doc_id={}", doc_id)
                return None
            if metadata.get("selector_version") != self._DOCX_TEMPLATE_SELECTOR_VERSION:
                logger.info("原格式模板缓存选择策略已变化，准备重新提取: doc_id={}", doc_id)
                return None

            with open(cache_path, "rb") as cache_file:
                cached_bytes = cache_file.read()
            if not cached_bytes:
                logger.warning("原格式模板缓存为空，准备重新提取: doc_id={}", doc_id)
                return None

            # 用 python-docx 做一次轻量完整性校验，避免把损坏缓存交给 Agent。
            Document(io.BytesIO(cached_bytes))
            source_mode = str(metadata.get("source_mode") or "native_docx")
            logger.info(
                "命中原格式模板缓存: doc_id={}, bytes={}, source_mode={}",
                doc_id,
                len(cached_bytes),
                source_mode,
            )
            return cached_bytes, f"cached_{source_mode}"
        except Exception as cache_error:
            logger.exception(
                "读取原格式模板缓存失败，将重新提取: doc_id={}, path={}, error={}",
                doc_id,
                cache_path,
                cache_error,
            )
            return None

    def _write_cached_bid_format_template(
        self,
        doc_id: str,
        source_file_path: str,
        docx_bytes: bytes,
        source_mode: str,
    ) -> None:
        """以原子替换方式保存原格式模板，供后续 Agent 进程直接复用。"""
        if not docx_bytes:
            return

        cache_path, metadata_path = self._get_bid_format_cache_paths(doc_id)
        cache_dir = os.path.dirname(cache_path)
        os.makedirs(cache_dir, exist_ok=True)
        cache_temp_path = f"{cache_path}.{uuid.uuid4().hex}.tmp"
        metadata_temp_path = f"{metadata_path}.{uuid.uuid4().hex}.tmp"
        try:
            with open(cache_temp_path, "wb") as cache_file:
                cache_file.write(docx_bytes)
            os.replace(cache_temp_path, cache_path)

            metadata = {
                "source_fingerprint": self._build_source_fingerprint(source_file_path),
                "source_mode": source_mode,
                "selector_version": self._DOCX_TEMPLATE_SELECTOR_VERSION,
            }
            with open(metadata_temp_path, "w", encoding="utf-8") as metadata_file:
                json.dump(metadata, metadata_file, ensure_ascii=False, indent=2)
            os.replace(metadata_temp_path, metadata_path)
            logger.info(
                "已缓存原格式 Word 模板: doc_id={}, path={}, source_mode={}",
                doc_id,
                cache_path,
                source_mode,
            )
        finally:
            for temporary_path in (cache_temp_path, metadata_temp_path):
                if os.path.exists(temporary_path):
                    try:
                        os.remove(temporary_path)
                    except OSError as cleanup_error:
                        logger.warning(
                            "清理原格式模板缓存临时文件失败: path={}, error={}",
                            temporary_path,
                            cleanup_error,
                        )

    def _cache_extracted_template(
        self,
        doc_id: str,
        source_file_path: str,
        docx_bytes: bytes,
        filename: str,
        mode: str,
    ) -> Tuple[bytes, str, str]:
        """缓存提取结果但不影响当前请求返回，缓存失败时保留当前业务结果。"""
        try:
            self._write_cached_bid_format_template(
                doc_id=doc_id,
                source_file_path=source_file_path,
                docx_bytes=docx_bytes,
                source_mode=mode,
            )
        except Exception as cache_error:
            logger.exception(
                "保存原格式模板缓存失败，但不影响本次导出: doc_id={}, error={}",
                doc_id,
                cache_error,
            )
        return docx_bytes, filename, mode

    def extract_and_export_bid_format(
        self, 
        db: Session, 
        doc_id: str,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        template_id: Optional[str] = None,
        force_reextract: bool = False,
    ) -> Tuple[bytes, str, str]:
        """
        全流程处理方法：根据 doc_id 获取文件类型并执行切片提取与 Word 导出。

        :param db: 数据库 Session
        :param doc_id: 文档 ID
        :param user_id: 用户 ID (可选)
        :param tenant_id: 租户 ID (可选)
        :param template_id: 指定外部空白模板 ID；不传则读取该文档当前绑定的模板
        :param force_reextract: 是否跳过已缓存的原格式模板并重新提取
        :return: (docx_bytes, filename, extraction_mode)
        """
        # 1. 检索文档记录
        if user_id and tenant_id:
            doc_obj = document_crud.get_document_by_id(db, doc_id, user_id=user_id, tenant_id=tenant_id)
        else:
            doc_obj = document_crud.get_document_by_id_system(db, doc_id)

        if not doc_obj or not doc_obj.file_path or not os.path.exists(doc_obj.file_path):
            logger.error(f"提取投标文件格式失败：找不到文档记录或原文件不存在 (doc_id={doc_id})")
            raise FileNotFoundError("找不到原始招标文件记录或存储路径")

        file_path = doc_obj.file_path
        effective_tenant_id = tenant_id or getattr(doc_obj, "tenant_id", None)
        file_ext = os.path.splitext(file_path)[1].lower()
        base_name = os.path.splitext(os.path.basename(doc_obj.filename))[0]
        export_filename = f"{base_name}_投标文件格式模板.docx"

        # 外部模板一旦绑定到招标文档，所有提取/填报入口默认复用该模板。
        # 这样前端不必在每个后续请求中重复传递模板标识，同时保留显式 template_id 的覆盖能力。
        try:
            from app.services.bid_template_service import bid_template_service

            bound_template = (
                bid_template_service.get_template(db, template_id, effective_tenant_id)
                if template_id
                else bid_template_service.get_bound_template(db, doc_id, effective_tenant_id)
            )
        except SQLAlchemyError as template_query_error:
            db.rollback()
            if template_id:
                logger.exception(
                    "读取指定外部投标模板失败: template_id={}, document_id={}, error={}",
                    template_id,
                    doc_id,
                    template_query_error,
                )
                raise FileNotFoundError("外部模板记录不可用，请确认数据库迁移已完成") from template_query_error
            logger.warning(
                "读取文档绑定模板失败，继续使用传统招标文件切片流程: document_id={}, error={}",
                doc_id,
                template_query_error,
            )
            bound_template = None

        if template_id and bound_template is None:
            raise FileNotFoundError("指定的外部模板不存在、已停用或无权访问")
        if bound_template is not None:
            external_template_path = str(bound_template.file_path or "")
            if not os.path.isfile(external_template_path):
                raise FileNotFoundError("绑定的外部模板文件不存在，请重新上传")
            try:
                with open(external_template_path, "rb") as external_template_file:
                    external_template_bytes = external_template_file.read()
                Document(io.BytesIO(external_template_bytes))
            except (OSError, ValueError, KeyError, zipfile.BadZipFile) as template_file_error:
                logger.exception(
                    "读取绑定外部模板失败: template_id={}, path={}, error={}",
                    bound_template.id,
                    external_template_path,
                    template_file_error,
                )
                raise FileNotFoundError("绑定的外部模板损坏，请重新上传") from template_file_error
            logger.info(
                "使用绑定的外部 DOCX 模板: document_id={}, template_id={}, bytes={}",
                doc_id,
                bound_template.id,
                len(external_template_bytes),
            )
            return external_template_bytes, export_filename, "bound_external_template"

        # 外部模板优先级最高；普通下载优先复用已提取缓存，明确重新提取时跳过缓存。
        if force_reextract:
            logger.info("收到重新提取投标文件模板请求，跳过原格式模板缓存: doc_id={}", doc_id)
        else:
            cached_template = self._read_cached_bid_format_template(doc_id, file_path)
            if cached_template:
                cached_bytes, cached_mode = cached_template
                return cached_bytes, export_filename, cached_mode

        # 2. 判断文件类型，优先使用原生 DOCX 切片模式
        if file_ext in ['.docx', '.doc']:
            target_docx_path = file_path
            try:
                if file_ext == '.doc':
                    logger.info(f"原生文件为 .doc，尝试使用 LibreOffice 转换为 .docx: {file_path}")
                    target_docx_path = self.extractor_service.convert_doc_to_docx(file_path)
            except Exception as conversion_error:
                logger.exception(
                    "Word 文件转换失败，无法继续执行原生结构切片或大模型章节定位: {}",
                    conversion_error,
                )
                target_docx_path = ""

            if target_docx_path:
                try:
                    docx_bytes = self._slice_docx_natively(target_docx_path)
                    if docx_bytes:
                        logger.info(f"原生 Word 切片成功！文件大小: {len(docx_bytes)} 字节")
                        return self._cache_extracted_template(
                            doc_id, file_path, docx_bytes, export_filename, "native_docx"
                        )
                except Exception as native_extract_error:
                    logger.exception(
                        "原生 Word DOM 切片执行异常，继续尝试大模型章节定位: {}",
                        native_extract_error,
                    )

                try:
                    logger.info("原生 Word 结构定位未命中，交由大模型从既有标题候选中定位")
                    located_docx_bytes = self._slice_docx_with_llm_locator(
                        target_docx_path,
                        tenant_id=effective_tenant_id,
                    )
                    if located_docx_bytes:
                        logger.info(
                            "大模型定位 Word 章节成功，已使用原始 DOM 切片，文件大小: {} 字节",
                            len(located_docx_bytes),
                        )
                        return self._cache_extracted_template(
                            doc_id,
                            file_path,
                            located_docx_bytes,
                            export_filename,
                            "llm_located_native_docx",
                        )
                except Exception as locator_error:
                    logger.exception(
                        "大模型 Word 章节定位执行异常: {}",
                        locator_error,
                    )

            # Word 定位失败时不生成基础模板，避免把与原文件无关的内容伪装成提取结果。
            if not target_docx_path:
                raise RuntimeError(
                    "Word 文件无法转换为 DOCX，未能执行原生结构切片或大模型章节定位"
                )
            raise RuntimeError(
                "未能通过原生 Word 结构或大模型章节定位投标文件格式，未生成基础模板"
            )

        # 3. 回退模式 / PDF 模式：利用 ExtractorService 与 LLM 重建标准 Word
        logger.info(f"使用 LLM 结构化提取模式处理文件: {file_path}")
        docx_bytes, mode = self._extract_with_llm_and_rebuild(
            db,
            doc_obj,
            tenant_id=effective_tenant_id,
        )
        return self._cache_extracted_template(doc_id, file_path, docx_bytes, export_filename, mode)

    def _is_toc_line(self, text: str, element=None) -> bool:
        """
        严密判定某个段落是否为目录页/导引线/目录项（TOC Line）
        """
        if not text:
            return False
        clean_txt = text.strip()

        # 1. 检查 XML 节点中是否包含 TOC / Hyperlink 目录特征
        if element is not None:
            try:
                xml_str = element.xml if hasattr(element, 'xml') else ""
                if 'w:hyperlink' in xml_str and '_Toc' in xml_str:
                    return True
                if 'w:pStyle' in xml_str and ('TOC' in xml_str or 'toc' in xml_str or '目录' in xml_str):
                    return True
                if 'w:fldSimple' in xml_str and 'TOC' in xml_str:
                    return True
                if 'w:instrText' in xml_str and 'TOC' in xml_str:
                    return True
            except Exception:
                pass

        # 2. 匹配目录导引线及页码 (如 ".......... -3-"、".......... 55"、".......... -55-"、"…… 40"、"...... 55页")
        if re.search(r'[\.….┈\-_]{2,}\s*[-–—\s]*\d+[-–—\s\.\)\]页]*$', clean_txt):
            return True

        # 3. 匹配包含多连点/制表符且末尾包含页码数字（兼容各种页码修饰符如 -55- 或 55页）
        if re.search(r'[\.….┈\-_]{2,}', clean_txt) and re.search(r'\d+[-–—\s\.\)\]页]*$', clean_txt):
            return True

        # 4. 匹配制表符或多连点后跟着页码数字（如 "第六章 投标文件格式  -55-"）
        if re.search(r'[\s\t]+[-–—\s]*\d+[-–—\s\.\)\]页]*$', clean_txt) and len(clean_txt) < 100:
            if re.search(r'[\.….┈\-_]', clean_txt) or '\t' in text:
                return True

        # 5. 纯目录卷标/目录标题行 (如 "第一卷"、"第二卷"、"第三卷"、"目  录")
        if re.search(r'^\s*(?:第[一二三四五六七八九十\d]+卷|目\s*录|Table\s*of\s*Contents)\s*$', clean_txt):
            return True

        return False

    def _is_real_next_main_chapter(self, text: str, element=None) -> bool:
        """
        判断某个段落是否为真正的下一个招标大章（如 第七章 评标办法 / 第七章 合同条款），
        避免误将“第六章 投标文件格式”内部的格式子项（如“格式七 授权书”、“附件七 承诺函”）判定为终点。
        """
        if not text:
            return False
        clean_txt = text.strip()

        # 如果属于目录行，直接排除
        if self._is_toc_line(clean_txt, element):
            return False

        # 匹配大章主标题模式，如 第七章、第八章 (兼容 Markdown # / ** / ## 标记与空格)
        main_chapter_pattern = re.compile(r'^[#\s\*]*第\s*[一二三四五六七八九十\d]+\s*[章篇部分卷]')
        if not main_chapter_pattern.search(clean_txt):
            return False

        # 排除包含格式附件关键词的内部子标题（如 格式、附件、表、样张、承诺、声明、证明、清单、函、明细、协议）
        internal_format_keywords = ['格式', '附件', '表', '样张', '承诺', '声明', '证明', '清单', '函', '明细', '协议', '响应', '授权']
        if any(kw in clean_txt for kw in internal_format_keywords):
            return False

        # 排除以子序号开头的条目，如 一、二、三、(一)、(1)
        if re.search(r'^\s*[\(（]?[一二三四五六七八九十\d]+[\)）\.\、]', clean_txt):
            return False

        return True

    def _slice_docx_natively(self, docx_path: str) -> Optional[bytes]:
        """
        核心方法：原生 Word DOM 节点裁剪算法。
        严密排除目录（TOC）与格式附件子标题干扰，精准提取“投标文件格式”正文全量内容与表格附件。
        """
        if not os.path.exists(docx_path):
            return None

        doc = Document(docx_path)
        body = doc._body._element

        start_index = -1
        end_index = -1

        # 遍历文本当中的所有子元素（包含 Paragraph 和 Table）
        children = list(body)
        
        # 建立段落文本与索引映射
        element_meta = []
        for idx, child in enumerate(children):
            tag_name = child.tag.split('}')[-1]
            text = ""
            if tag_name == 'p':
                text = "".join(child.itertext()).strip()
            element_meta.append({'index': idx, 'tag': tag_name, 'text': text, 'element': child})

        # 寻找起始大章（必须排除目录 TOC 行）
        candidate_starts = []
        for item in element_meta:
            txt = item['text']
            elem = item['element']
            if any(pat.search(txt) for pat in self.chapter_start_patterns):
                if not self._is_toc_line(txt, elem):
                    candidate_starts.append(item['index'])
                    logger.info(f"发现正文候选起始位置: line {item['index']} -> '{txt[:40]}'")

        if len(candidate_starts) == 1:
            start_index = candidate_starts[0]
            logger.info(f"锁定投标文件格式正文起始位置: line {start_index}")
        elif candidate_starts:
            logger.info(
                "发现多个非目录投标格式候选，交由大模型章节定位: candidates={}",
                candidate_starts,
            )
            return None
        else:
            logger.warning("未能在原生 Word 中匹配到非目录的'投标文件格式'正文起始位置")
            return None

        # 寻找结束界限（从 start_index + 1 开始，下一个真正的独立大章标题，或者文件末尾）
        for item in element_meta[start_index + 1:]:
            txt = item['text']
            elem = item['element']
            if self._is_real_next_main_chapter(txt, elem):
                end_index = item['index']
                logger.info(f"定位到下一个独立大章终止位置: line {end_index} -> '{txt[:40]}'")
                break

        if end_index == -1:
            end_index = len(children)
            logger.info("投标文件格式章节无后续主大章，全量延伸提取至文件末尾")

        # 提取切片范围元素
        target_elements = children[start_index:end_index]
        if not target_elements:
            return None

        # 【核心防护】：自动剪除切片头部残留的目录行、卷标行或导引线节点 (如 "第一卷"、"第一章 招标公告...-3-" 等)
        while target_elements:
            first_txt = "".join(target_elements[0].itertext()).strip()
            if self._is_toc_line(first_txt, target_elements[0]):
                logger.info(f"   ✂️ 自动剪除切片头部残留目录节点: '{first_txt[:50]}'")
                target_elements.pop(0)
            else:
                break

        if not target_elements:
            return None

        logger.info(f"成功裁剪投标文件格式正文切片！包含 {len(target_elements)} 个 DOM 元素节点")

        # 清空 body 中的非切片节点
        for child in list(body):
            if child not in target_elements and child.tag.endswith(('p', 'tbl')):
                body.remove(child)

        # 全量修改所有文字 Run 为黑色字体 (RGB 0,0,0)
        black_color = RGBColor(0, 0, 0)
        for p in doc.paragraphs:
            for run in p.runs:
                run.font.color.rgb = black_color

        for t in doc.tables:
            for row in t.rows:
                for cell in row.cells:
                    for p in cell.paragraphs:
                        for run in p.runs:
                            run.font.color.rgb = black_color

        # 输出为字节流
        output = io.BytesIO()
        doc.save(output)
        output.seek(0)
        return output.getvalue()

    def _export_docx_elements(
        self,
        doc: Any,
        body: Any,
        target_elements: List[Any],
    ) -> Optional[bytes]:
        """
        将选定的原始 Word body 节点导出为 DOCX 字节流。

        该方法只做 DOM 保留与格式颜色统一，不生成或改写正文内容。
        """
        if not target_elements:
            return None

        # 清空 body 中的非切片节点，但保留 sectPr 等文档级节点。
        for child in list(body):
            if child not in target_elements and child.tag.endswith(("p", "tbl")):
                body.remove(child)

        # 延续原有输出规则，将保留片段中的文字统一为黑色。
        black_color = RGBColor(0, 0, 0)
        for paragraph in doc.paragraphs:
            for run in paragraph.runs:
                run.font.color.rgb = black_color

        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for paragraph in cell.paragraphs:
                        for run in paragraph.runs:
                            run.font.color.rgb = black_color

        output = io.BytesIO()
        doc.save(output)
        output.seek(0)
        return output.getvalue()

    def _extract_docx_heading_candidates(self, docx_path: str) -> List[Dict[str, Any]]:
        """
        复用现有 DocxParser 标题提取结果，并补充目录标记和正文上下文。

        body_index 是原始 XML body 节点索引，后续只允许在这些候选节点之间做切片，
        防止大模型自行编造标题或正文边界。
        """
        docx_parser = self.extractor_service._get_docx_parser()
        parser_candidates = docx_parser.extract_heading_candidates(docx_path)
        document = Document(docx_path)
        body_children = list(document._body._element)
        candidates: List[Dict[str, Any]] = []

        for parser_candidate in parser_candidates:
            body_index = int(parser_candidate["body_index"])
            if body_index < 0 or body_index >= len(body_children):
                logger.warning(
                    "忽略超出 Word body 范围的标题候选: file={}, body_index={}",
                    docx_path,
                    body_index,
                )
                continue

            element = body_children[body_index]
            title = str(parser_candidate.get("title") or "").strip()
            context_parts: List[str] = []
            for next_element in body_children[body_index + 1:]:
                next_text = "".join(next_element.itertext()).strip()
                if not next_text:
                    continue
                context_parts.append(next_text[:300])
                if len(context_parts) >= 6:
                    break

            normalized_title = self.extractor_service._normalize_title_for_matching(title)
            candidates.append(
                {
                    **parser_candidate,
                    "normalized_title": normalized_title,
                    "is_toc": self._is_toc_line(title, element),
                    "context_after": " | ".join(context_parts)[:1200],
                }
            )

        logger.info(
            "Word 标题候选增强完成: file={}, total={}, usable={}",
            docx_path,
            len(candidates),
            sum(1 for candidate in candidates if not candidate["is_toc"]),
        )
        return candidates

    def _locate_docx_format_chapter_with_llm(
        self,
        docx_path: str,
        tenant_id: Optional[str] = None,
    ) -> Optional[Tuple[int, Optional[int]]]:
        """
        让大模型仅从既有标题候选中选择投标文件格式章节的起止节点。

        返回原始 body 节点索引；任何未验证的标题、正文或边界都不会被采用。
        """
        if not self.llm_service.is_configured_for_tenant(tenant_id):
            logger.warning("Word 章节定位所需模型不可用：租户未完成模型配置: {}", tenant_id)
            raise ModelUnavailableError("模型不可用：尚未配置有效的模型服务")

        candidates = self._extract_docx_heading_candidates(docx_path)
        usable_candidates = [candidate for candidate in candidates if not candidate["is_toc"]]
        if not usable_candidates:
            logger.warning("Word 中没有可供大模型判断的非目录标题候选: {}", docx_path)
            return None

        candidate_payload = [
            {
                "candidate_id": candidate["candidate_id"],
                "title": candidate["title"],
                "normalized_title": candidate["normalized_title"],
                "heading_level": candidate["heading_level"],
                "candidate_kind": candidate["candidate_kind"],
                "context_after": candidate["context_after"],
            }
            for candidate in usable_candidates
        ]
        prompt = f"""
你是招标文件 Word 章节定位器。你的唯一任务是从下方候选标题中定位“投标文件格式、应答文件格式、响应文件格式、投标文件组成或格式及附件”正文大章。

严格规则：
1. 只能返回候选列表中已经存在的 candidate_id，禁止编造标题、正文或索引。
2. 必须排除目录候选；起始标题可以使用不同表述，例如带书名号、括号或“编制要求”的标题。
3. start_candidate_id 选择格式章节标题本身；end_candidate_id 选择其后的下一个同级或更高层级主章节标题，不属于格式章节的附件标题不能作为结束点。
4. 如果没有明确证据，matched=false，两个 ID 返回 null，confidence 返回 0。
5. 只有在标题或其后上下文出现投标函、报价、授权、法定代表人、偏离表、承诺书、资格审查、商务响应、技术响应、格式附件等线索时，才可以判定为 matched=true。

只返回 JSON：
{{
  "matched": true,
  "start_candidate_id": "候选 ID 或 null",
  "end_candidate_id": "候选 ID 或 null",
  "confidence": 0.0,
  "reason": "简要依据"
}}

候选标题列表：
{json.dumps(candidate_payload, ensure_ascii=False)}
""".strip()

        try:
            raw_result = self.llm_service.generate_structured_json(
                prompt,
                temperature=0.0,
                tenant_id=tenant_id,
            )
            locator_result = BidFormatLocatorResult.model_validate(raw_result)
        except ModelUnavailableError:
            raise
        except (ValidationError, ValueError, TypeError) as locator_error:
            logger.warning("大模型 Word 章节定位结果无效，放弃定位: {}", locator_error)
            return None
        except Exception as llm_error:
            logger.exception("调用大模型定位 Word 章节失败，模型不可用: {}", llm_error)
            raise ModelUnavailableError(
                "模型不可用：模型服务连接失败，请检查模型地址、网络或服务状态"
            ) from llm_error

        if not locator_result.matched or locator_result.confidence < 0.85:
            logger.warning(
                "大模型未提供足够可信的 Word 章节定位结果: matched={}, confidence={}, reason={}",
                locator_result.matched,
                locator_result.confidence,
                locator_result.reason,
            )
            return None

        candidate_map = {candidate["candidate_id"]: candidate for candidate in usable_candidates}
        start_candidate = candidate_map.get(locator_result.start_candidate_id or "")
        end_candidate = (
            candidate_map.get(locator_result.end_candidate_id or "")
            if locator_result.end_candidate_id
            else None
        )
        if start_candidate is None:
            logger.warning("大模型返回的起始标题不在候选列表中: {}", locator_result.start_candidate_id)
            return None

        start_index = int(start_candidate["body_index"])
        end_index = int(end_candidate["body_index"]) if end_candidate else None
        if end_index is not None and end_index <= start_index:
            logger.warning(
                "大模型返回的章节边界顺序无效: start={}, end={}",
                start_index,
                end_index,
            )
            return None

        evidence_text = " ".join(
            [
                str(start_candidate.get("title") or ""),
                str(start_candidate.get("context_after") or ""),
            ]
        )
        if not any(marker in evidence_text for marker in self.format_body_markers):
            logger.warning("大模型定位结果缺少投标格式正文证据，放弃原始切片: {}", evidence_text[:200])
            return None

        logger.info(
            "大模型锁定 Word 投标格式章节: start={}, end={}, confidence={}, reason={}",
            start_candidate["title"],
            end_candidate["title"] if end_candidate else "文档末尾",
            locator_result.confidence,
            locator_result.reason,
        )
        return start_index, end_index

    def _slice_docx_with_llm_locator(
        self,
        docx_path: str,
        tenant_id: Optional[str] = None,
    ) -> Optional[bytes]:
        """
        根据大模型选出的候选节点，在原始 Word DOM 中执行无损切片。
        """
        located_range = self._locate_docx_format_chapter_with_llm(docx_path, tenant_id=tenant_id)
        if located_range is None:
            return None

        start_index, end_index = located_range
        document = Document(docx_path)
        body = document._body._element
        children = list(body)
        if start_index < 0 or start_index >= len(children):
            logger.warning("大模型定位的起始 body 索引越界: {}", start_index)
            return None

        exclusive_end = end_index if end_index is not None else len(children)
        if exclusive_end <= start_index or exclusive_end > len(children):
            logger.warning("大模型定位的结束 body 索引无效: {}", exclusive_end)
            return None

        target_elements = children[start_index:exclusive_end]
        while target_elements:
            first_text = "".join(target_elements[0].itertext()).strip()
            if self._is_toc_line(first_text, target_elements[0]):
                logger.info("自动剪除大模型切片头部目录节点: {}", first_text[:50])
                target_elements.pop(0)
            else:
                break

        if not target_elements:
            return None

        logger.info("大模型定位后使用原始 Word DOM 切片，元素数量={}", len(target_elements))
        return self._export_docx_elements(document, body, target_elements)

    def _extract_with_llm_and_rebuild(
        self,
        db: Session,
        doc_obj,
        tenant_id: Optional[str] = None,
    ) -> Tuple[bytes, str]:
        """
        LLM 提取模式：结合 ExtractorService 与 LLM 提取文本，并用 DocxExporterService 渲染 Word。

        :param tenant_id: 调用方显式传入的租户 ID；未传入时回退使用文档所属租户。
        :return: (docx_bytes, actual_mode)，成功时 actual_mode 为 "llm_rebuilt"
        """
        # 显式保留租户上下文，避免线程池调用时 ContextVar 丢失而回退到全局模型配置。
        effective_tenant_id = tenant_id or getattr(doc_obj, "tenant_id", None)

        # 读取文本
        md_file_path = (
            doc_obj.parsed_metadata.get("md_file_path", "")
            if doc_obj and doc_obj.parsed_metadata
            else ""
        )
        doc_text = ""
        if md_file_path and os.path.exists(md_file_path):
            with open(md_file_path, "r", encoding="utf-8") as f:
                doc_text = f.read()
            logger.info(f"成功读取 Markdown 缓存文件: {md_file_path} (文本总长度: {len(doc_text)} 字符)")
        else:
            chunks = document_crud.get_document_chunks(db, doc_obj.id)
            doc_text = "\n\n".join([c.content for c in chunks]) if chunks else ""
            logger.info(f"从数据库切片提取文本完成 (共 {len(chunks) if chunks else 0} 个切片, 文本总长度: {len(doc_text)} 字符)")

        if not doc_text.strip():
            logger.error("⚠️ [投标文件格式提取] 文档未提取到任何有效文本，无法交由大模型定位目标章节")
            raise ValueError("原始招标文件未提取到有效文本，无法执行投标文件格式提取")

        # 正则快速定位文本范围
        target_text = self._slice_text_by_keywords(doc_text)
        is_full_text_fallback = not target_text.strip()
        if not target_text.strip():
            # 规则定位只是缩小大模型搜索范围，不能作为是否调用大模型的硬门槛。
            target_text = doc_text
            logger.warning(
                "⚠️ [投标文件格式提取] 规则未定位到目标章节，将全文交由大模型自行定位: text_length={}",
                len(doc_text),
            )

        if is_full_text_fallback:
            source_scope_instruction = (
                "规则定位未命中，当前待分析文本为原始文档全文。请先在全文中自行定位投标文件格式相关正文大章，"
                "再仅提取该章节及其格式附件，不得把其他章节内容混入结果。"
            )
        else:
            source_scope_instruction = (
                "系统已通过规则定位出目标格式章节范围。请仅在该范围内提取内容，"
                "不得引入范围外的其他章节。"
            )

        # 构建 Prompt 引导 LLM 输出结构化数据
        prompt = f"""你是一名资深招投标专家。请分析以下招标文件中的“投标文件格式/响应格式”部分文本，严格依据原文提取出完整的格式附件目录与样张模版。

【最高指令】:
1. 100% 忠实于【待分析文本】原文提取，严禁凭常识臆造或捏造原文不存在的附件名称、字段或内容。
2. 提取文本中出现的全部格式附件标题（如各类格式、附件、声明、承诺、样张等，严格以原文实际标题为准）。
3. 原文中的表格（无论以 Markdown 表格还是 HTML <table> 形式出现）必须完整保留其行列表格结构（转换为标准 Markdown 表格输出），原文中的填空下划线 `______` 必须完整保留。
4. 必须将原文中每个格式附件的完整正文、填空要素和表格内容原原本本提取并放入 `body_markdown`，严禁输出“原文未提供样张”等概括性文字。
5. {source_scope_instruction}
6. 如果全文中确实没有投标文件格式相关正文，返回空的 `sections`，不要用常识补写模板内容。

【待分析文本】:
{target_text[:40000]}

【提取要求与结构定义】:
`content_type` 字段可选值：'form_table' (表格样张/填报明细)、'text_template' (公文/承诺书/证明模板)、'checklist' (清单/目录)、'other' (其他格式附件)。
请返回合法 JSON 格式对象（只输出纯 JSON，不要包含任何前导或后置解释说明），严格符合以下数据结构定义：
{{
  "document_title": "{doc_obj.filename} - 投标文件格式模板",
  "source_chapter_name": "投标文件格式",
  "sections": [
     {{
        "section_title": "原文中的格式附件标题",
        "content_type": "text_template",
        "body_markdown": "原文中的模板正文内容或 Markdown 表格内容（完整保留填空下划线 ______）",
        "placeholders": ["从该格式中提炼出的待填空字段名"]
     }}
  ]
}}
"""
        try:
            if self.llm_service.is_configured_for_tenant(effective_tenant_id):
                logger.info(f"🚀 [投标文件格式提取] 正在调用 LLM 结构化提取招标文件格式 (待分析切片长度: {len(target_text[:40000])} 字符)...")
                parsed_json = self.llm_service.generate_structured_json(
                    prompt,
                    temperature=0.1,
                    tenant_id=effective_tenant_id,
                )
                # 若大模型直接返回了 sections 数组，自动包装为字典对象
                if isinstance(parsed_json, list):
                    parsed_json = {
                        "document_title": f"{doc_obj.filename} - 投标文件格式模板",
                        "source_chapter_name": "投标文件格式",
                        "sections": parsed_json
                    }
                structure = BidFormatStructure(**parsed_json)
                if not structure.sections:
                    logger.warning("⚠️ [投标文件格式提取] 大模型未在原文中定位到可用的投标文件格式章节")
                    raise ValueError("大模型未在原文中定位到可用的投标文件格式章节")
                else:
                    section_names = [s.section_title for s in structure.sections]
                    logger.info(f"✅ [投标文件格式提取] LLM 结构化提取成功！共提取出 {len(structure.sections)} 个格式附件: {section_names}")
                    return docx_exporter_service.export_bid_format_to_docx_bytes(structure), "llm_rebuilt"
            else:
                logger.warning("⚠️ [投标文件格式提取] LLM 服务未配置，模型不可用")
                raise ModelUnavailableError("模型不可用：尚未配置有效的模型服务")
        except ModelUnavailableError:
            raise
        except (ValidationError, ValueError, TypeError) as result_error:
            logger.exception(
                "❌ [投标文件格式提取] 大模型返回结果无法作为有效模板使用: {}",
                result_error,
            )
            raise ValueError(f"大模型未能生成有效的投标文件格式模板: {result_error}") from result_error
        except Exception as e:
            logger.exception(f"❌ [投标文件格式提取] LLM 提取或解析过程发生异常: {str(e)}")
            raise ModelUnavailableError(
                "模型不可用：模型服务调用失败，请检查模型地址、网络或服务状态"
            ) from e

    def _slice_text_by_keywords(self, full_text: str) -> str:
        """
        在纯文本中截取“投标文件格式/应答文件格式”章节。

        先从所有同名标题中选择最像正文的候选项，再截取至下一个独立大章。
        未定位到目标章节时返回空字符串，由上层将全文交给 LLM 自行定位。
        """
        if not full_text or not full_text.strip():
            logger.warning("⚠️ [投标文件格式提取] 输入文本为空，无法定位目标章节")
            return ""

        lines = full_text.splitlines()
        candidate_indices = [
            index
            for index, line in enumerate(lines)
            if any(pattern.search(line.strip()) for pattern in self.chapter_start_patterns)
        ]
        if not candidate_indices:
            logger.warning("⚠️ [投标文件格式提取] 未定位到目标章节标题，交由上层将全文交给 LLM 定位")
            return ""

        # 优先使用目录中出现的章节身份（如“第九章”），再到正文查找同一章节，章节编号由原文动态决定。
        toc_chapter_keys = self._find_toc_target_chapter_keys(lines)
        if toc_chapter_keys:
            toc_matched_candidates = [
                index
                for index in candidate_indices
                if not self._is_toc_line(lines[index])
                and self._chapter_identity_key(lines[index]) in toc_chapter_keys
            ]
            if toc_matched_candidates:
                candidate_indices = toc_matched_candidates
                logger.info(f"🔍 [投标文件格式提取] 根据目录动态锁定目标章节: {sorted(toc_chapter_keys)}")

        start_idx = max(candidate_indices, key=lambda index: self._score_text_chapter_candidate(lines, index))
        if self._is_toc_line(lines[start_idx]):
            logger.warning(
                f"⚠️ [投标文件格式提取] 目标标题仅命中目录行: '{lines[start_idx].strip()}'，交由上层将全文交给 LLM 定位"
            )
            return ""

        end_idx = len(lines)
        for index in range(start_idx + 1, len(lines)):
            line_str = lines[index].strip()
            if self._is_real_next_main_chapter(line_str):
                end_idx = index
                logger.info(f"🔍 [投标文件格式提取] 定位到下一个独立大章终止行 (第 {index + 1} 行): '{line_str[:50]}'")
                break

        slice_lines = lines[start_idx:end_idx]
        while slice_lines and self._is_toc_line(slice_lines[0]):
            slice_lines.pop(0)
        logger.info(f"🔍 [投标文件格式提取] 成功定位正文起始行 (第 {start_idx + 1} 行), 切片行数: {len(slice_lines)}")
        return "\n".join(slice_lines)

    def _score_text_chapter_candidate(self, lines: List[str], index: int) -> tuple[int, int]:
        """为章节标题候选项评分，优先选择包含格式正文特征的正文而非目录。"""
        line = lines[index].strip()
        context_before = "\n".join(lines[max(0, index - 8):index + 1])
        context_after = "\n".join(lines[index + 1:index + 36])
        score = 0
        if self._is_toc_line(line):
            score -= 100
        if re.search(r'目录|contents', context_before, re.IGNORECASE):
            score -= 30
        marker_hits = sum(marker in context_after for marker in self.format_body_markers)
        score += min(marker_hits, 4) * 8
        # 同分时取靠后的候选，避免目录中的同名标题遮蔽正文标题。
        return score, index

    def _chapter_identity_key(self, text: str) -> str:
        """提取章节编号作为动态匹配键，不绑定具体的章号。"""
        match = re.match(r'^[#\s\*]*(第\s*[一二三四五六七八九十\d]+\s*[章篇部分卷])', text.strip())
        if not match:
            return ""
        return re.sub(r'\s+', '', match.group(1))

    def _find_toc_target_chapter_keys(self, lines: List[str]) -> set[str]:
        """从目录行中提取目标格式章节身份，供正文定位动态复用。"""
        chapter_keys = {
            self._chapter_identity_key(line)
            for line in lines
            if self._is_toc_line(line)
            and any(pattern.search(line.strip()) for pattern in self.chapter_start_patterns)
        }
        return {key for key in chapter_keys if key}

    def _build_fallback_structure(self, filename: str) -> BidFormatStructure:
        """
        当未配置 LLM 或提取异常时的托底基础模板结构
        """
        base_title = os.path.splitext(filename)[0]
        return BidFormatStructure(
            document_title=f"{base_title} - 投标文件格式",
            source_chapter_name="应答文件格式",
            sections=[
                BidFormatSection(
                    section_title="附件一：投标函",
                    content_type=ContentTypeEnum.TEXT_TEMPLATE,
                    body_markdown="致：_____________________（招标人名称）\n\n1. 我方已仔细研究了_____________________（项目名称及招标编号）招标文件的全部内容，遵照招标文件要求，我方愿以人民币（大写）____________________（￥_________元）的投标总价，按合同约定实施和完成各项工作。\n\n2. 我方承诺本投标文件有效期为开标之日起_______天。\n\n投标人名称（盖章）：_____________________\n法定代表人或授权委托人（签字/盖章）：_____________________\n日期：______年___月___日",
                    placeholders=["招标人名称", "项目名称", "投标总价", "有效期天数"]
                ),
                BidFormatSection(
                    section_title="附件二：法定代表人授权委托书",
                    content_type=ContentTypeEnum.TEXT_TEMPLATE,
                    body_markdown="本授权声明：正式授权_________________（代理人姓名）为我方合法代理人，以我方名义签署、澄清、说明_____________________项目（招标编号：_____________）的投标文件，并处理一切与该项目投标有关的事宜。\n\n委托期限：自本授权书签署之日起至投标有效期届满止。\n\n法定代表人（签字/盖章）：_____________________\n身份证号码：_____________________\n授权委托人（签字/盖章）：_____________________\n身份证号码：_____________________\n投标人名称（盖大公章）：_____________________",
                    placeholders=["代理人姓名", "项目名称", "身份证号码"]
                ),
                BidFormatSection(
                    section_title="附件三：开标一览表（报价汇总表）",
                    content_type=ContentTypeEnum.FORM_TABLE,
                    body_markdown="| 项目名称 | 投标总价（元） | 工期/交货期 | 质量标准 | 备注 |\n| :--- | :--- | :--- | :--- | :--- |\n| _____________________ | ￥________________ | ______日历天 | 合格 | 详见分项报价表 |",
                    placeholders=["投标总价", "工期"]
                )
            ]
        )


# 单例初始化
bid_format_extractor_service = BidFormatExtractorService()
