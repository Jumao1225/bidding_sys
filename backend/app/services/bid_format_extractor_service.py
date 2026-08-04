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
from typing import Tuple, Optional, List
from loguru import logger
from sqlalchemy.orm import Session
from docx import Document
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls
from docx.shared import RGBColor, Pt, Inches

from app.db.crud.document import document_crud
from app.services.extractor_service import ExtractorService
from app.services.docx_exporter_service import docx_exporter_service
from app.services.llm_service import LLMService
from app.schemas.bid_generator import (
    BidFormatStructure,
    BidFormatSection,
    ContentTypeEnum
)


class BidFormatExtractorService:
    """
    投标文件格式提取与导出核心业务服务
    """

    def __init__(self):
        self.extractor_service = ExtractorService()
        self.llm_service = LLMService()

        # 匹配“投标文件格式”大章标题正则表达式探照灯
        self.chapter_start_patterns = [
            re.compile(r'^\s*第[一二三四五六七八九十\d]+[章篇部分]\s*(投标文件格式|响应文件格式|投标文件组成|格式及附件|投标文件格式要求)'),
            re.compile(r'^\s*(投标文件格式|响应文件格式|投标文件格式及附件)\s*$'),
            re.compile(r'^\s*附[件录]\s*.*(投标文件格式|响应文件格式)'),
        ]

        # 匹配下一个大章（用于判定“投标文件格式”章节的终止界限）
        self.chapter_next_patterns = [
            re.compile(r'^\s*第[一二三四五六七八九十\d]+[章篇部分]\s*'),
        ]

    def extract_and_export_bid_format(
        self, 
        db: Session, 
        doc_id: str,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None
    ) -> Tuple[bytes, str, str]:
        """
        全流程处理方法：根据 doc_id 获取文件类型并执行切片提取与 Word 导出。

        :param db: 数据库 Session
        :param doc_id: 文档 ID
        :param user_id: 用户 ID (可选)
        :param tenant_id: 租户 ID (可选)
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
        file_ext = os.path.splitext(file_path)[1].lower()
        base_name = os.path.splitext(os.path.basename(doc_obj.filename))[0]
        export_filename = f"{base_name}_投标文件格式模板.docx"

        # 2. 判断文件类型，优先使用原生 DOCX 切片模式
        if file_ext in ['.docx', '.doc']:
            try:
                target_docx_path = file_path
                if file_ext == '.doc':
                    logger.info(f"原生文件为 .doc，尝试使用 LibreOffice 转换为 .docx: {file_path}")
                    target_docx_path = self.extractor_service.convert_doc_to_docx(file_path)

                docx_bytes = self._slice_docx_natively(target_docx_path)
                if docx_bytes:
                    logger.info(f"原生 Word 切片成功！文件大小: {len(docx_bytes)} 字节")
                    return docx_bytes, export_filename, "native_docx"
            except Exception as e:
                logger.warning(f"原生 Word 切片未命中或执行异常，回退至 LLM 重建模式: {str(e)}")

        # 3. 回退模式 / PDF 模式：利用 ExtractorService 与 LLM 重建标准 Word
        logger.info(f"使用 LLM 结构化提取模式处理文件: {file_path}")
        docx_bytes = self._extract_with_llm_and_rebuild(db, doc_obj)
        return docx_bytes, export_filename, "llm_rebuilt"

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

        # 匹配大章主标题模式，如 第七章、第八章
        main_chapter_pattern = re.compile(r'^\s*第[一二三四五六七八九十\d]+[章篇]\s*')
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

        if candidate_starts:
            # 锁定正文起始位置
            start_index = candidate_starts[0]
            logger.info(f"锁定投标文件格式正文起始位置: line {start_index}")
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

    def _extract_with_llm_and_rebuild(self, db: Session, doc_obj) -> bytes:
        """
        LLM 提取模式：结合 ExtractorService 与 LLM 提取文本，并用 DocxExporterService 渲染 Word。
        """
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
        else:
            chunks = document_crud.get_document_chunks(db, doc_obj.id)
            doc_text = "\n\n".join([c.content for c in chunks]) if chunks else ""

        if not doc_text.strip():
            logger.warning("文档未提取到任何有效文本，使用备用基础模板数据构建")
            structure = self._build_fallback_structure(doc_obj.filename)
            return docx_exporter_service.export_bid_format_to_docx_bytes(structure)

        # 正则快速定位文本范围
        target_text = self._slice_text_by_keywords(doc_text)

        # 构建 Prompt 引导 LLM 输出结构化数据
        prompt = f"""你是一名资深招投标专家。请分析以下招标文件中的“投标文件格式/响应格式”部分文本，提取出全套格式附件目录与样张模版。

【待分析文本】:
{target_text[:15000]}

【提取要求】:
1. 提取所有格式附件标题（如“附件一 投标函”、“附件二 法定代表人授权书”、“开标一览表”等）。
2. 保留原文中的表格（用 Markdown 表格表示）和待填写下划线 `______`。
3. 返回 JSON 格式，严格符合以下结构：
{{
  "document_title": "{doc_obj.filename} - 投标文件格式模板",
  "source_chapter_name": "投标文件格式",
  "sections": [
     {{
        "section_title": "附件一 投标函",
        "content_type": "text_template",
        "body_markdown": "致：[招标人名称]\\n\\n我方收到贵方关于......",
        "placeholders": ["招标人名称", "投标总价"]
     }}
  ]
}}
"""
        try:
            if self.llm_service.is_configured and self.llm_service.llm:
                response = self.llm_service.llm.invoke(prompt)
                res_content = response.content if hasattr(response, 'content') else str(response)
                import json
                parsed_json = json.loads(res_content)
                structure = BidFormatStructure(**parsed_json)
                logger.info(f"LLM 结构化提取格式成果，包含 {len(structure.sections)} 个格式附件")
            else:
                structure = self._build_fallback_structure(doc_obj.filename)
        except Exception as e:
            logger.error(f"LLM 提取投标文件格式 JSON 解析失败: {str(e)}，回退至基础结构")
            structure = self._build_fallback_structure(doc_obj.filename)

        return docx_exporter_service.export_bid_format_to_docx_bytes(structure)

    def _slice_text_by_keywords(self, full_text: str) -> str:
        """
        在纯文本中截取“投标文件格式”章节（自动排除目录 TOC 行）
        """
        lines = full_text.split('\n')
        start_idx = -1
        for i, l in enumerate(lines):
            if any(pat.search(l) for pat in self.chapter_start_patterns):
                if not self._is_toc_line(l):
                    start_idx = i
                    break

        if start_idx != -1:
            slice_lines = lines[start_idx:]
            while slice_lines and self._is_toc_line(slice_lines[0]):
                slice_lines.pop(0)
            return "\n".join(slice_lines)
        return full_text

    def _build_fallback_structure(self, filename: str) -> BidFormatStructure:
        """
        当未配置 LLM 或提取异常时的托底基础模板结构
        """
        base_title = os.path.splitext(filename)[0]
        return BidFormatStructure(
            document_title=f"{base_title} - 投标文件格式",
            source_chapter_name="第六章 投标文件格式",
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
