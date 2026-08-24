"""
样式定向文本提取工具 (Style Extractor Agent Tool)
允许 Agent 根据 document_id 或 file_path，结合章节名称与精细字体样式（如：斜体+下划线、加粗、红字等）进行精准过滤提取。
"""

import os
import docx
from typing import List, Dict, Any, Optional
from docx.document import Document as DocxDocument
from docx.table import Table
from docx.text.paragraph import Paragraph
from langchain_core.tools import tool
from loguru import logger


def resolve_document_file_path(target: str) -> Optional[str]:
    """
    智能解析 target 字符串为真实的物理磁盘文件路径：
    1. 若 target 为直接存在的磁盘文件，直接返回绝对路径；
    2. 若 target 为 UUID / document_id，去数据库 Document 表查询关联的 file_path；
    3. 若原始文件为 .doc，优先使用已转换好的 .docx 文件。
    """
    if not target:
        return None

    target = str(target).strip()

    # 1. 尝试直接作为磁盘路径
    abs_path = os.path.abspath(target)
    if os.path.isfile(abs_path):
        if abs_path.endswith(".doc") and os.path.isfile(abs_path + "x"):
            return abs_path + "x"
        return abs_path

    # 2. 从数据库中基于 document_id 进行智能路由解析
    try:
        from app.db.session import SessionLocal
        from app.db.models.project import Document as DocumentModel

        db = SessionLocal()
        try:
            doc = db.query(DocumentModel).filter(DocumentModel.id == target).first()
            if doc and doc.file_path:
                fp = os.path.abspath(doc.file_path)
                if os.path.isfile(fp):
                    if fp.endswith(".doc") and os.path.isfile(fp + "x"):
                        return fp + "x"
                    return fp

                # 如果数据库中存储的是相对路径，补全基准路径
                if not os.path.isabs(doc.file_path):
                    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
                    possible_path = os.path.abspath(os.path.join(backend_dir, doc.file_path))
                    if os.path.isfile(possible_path):
                        if possible_path.endswith(".doc") and os.path.isfile(possible_path + "x"):
                            return possible_path + "x"
                        return possible_path
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"智能解析 document_id '{target}' 的磁盘路径失败: {str(e)}")

    return None


def _iter_document_blocks(document: DocxDocument):
    """按 Word 文档实际顺序遍历正文段落和表格，避免章节上下文错位。"""
    body = document.element.body
    for element in body.iterchildren():
        if element.tag.endswith("}p"):
            yield Paragraph(element, document)
        elif element.tag.endswith("}tbl"):
            yield Table(element, document)


def _iter_table_paragraphs(table: Table):
    """遍历表格所有单元格中的段落，覆盖响应对照表等表格内容。"""
    for row in table.rows:
        for cell in row.cells:
            yield from cell.paragraphs


def _match_style(run: Any, style_type: str) -> bool:
    """判断单个 Run 是否符合指定的字体样式。"""
    is_bold = bool(run.bold)
    is_italic = bool(run.italic)
    is_underline = bool(run.underline)

    if style_type == "italic_underline":
        return is_italic and is_underline
    if style_type == "bold":
        return is_bold
    if style_type == "italic":
        return is_italic
    if style_type == "underline":
        return is_underline
    if style_type == "bold_red":
        color_rgb = str(run.font.color.rgb) if (run.font and run.font.color and run.font.color.rgb) else ""
        return is_bold and "FF0000" in color_rgb.upper()
    return False


@tool
def extract_text_by_style(
    document_id: Optional[str] = None,
    file_path: Optional[str] = None,
    chapter_keyword: Optional[str] = None,
    style_type: str = "italic_underline"
) -> str:
    """
    【样式定向文本提取工具】
    当你需要从 Word 招标文件 (.docx) 中精确定位特定格式属性的句子时（例如“参考第四章中斜体且带有下划线的文字”），请调用此工具。
    支持直接传入 document_id，系统会自动检索对应的 Word 物理文件磁盘路径！

    参数:
      - document_id: 当前招投标文档ID (优先推荐传入！如 "d55ae462-a1a5-4048-91a4-c57e3099ea74")
      - file_path: Word 文档的绝对路径 (可选，若无 document_id 时传入)
      - chapter_keyword: 目标章节关键词（可选，例如 "第四章"、"技术规范"、"投标人须知"），若为空则检索全篇
      - style_type: 期望筛选的样式类型，可选值:
          * "italic_underline" (斜体且带下划线，默认)
          * "bold" (仅加粗)
          * "italic" (仅斜体)
          * "underline" (仅下划线)
          * "bold_red" (红色加粗/废标红线)
    """
    raw_target = document_id or file_path
    if not raw_target:
        return "错误：必须至少提供 document_id 或 file_path 中的任意一个参数。"

    real_file_path = resolve_document_file_path(raw_target)

    # 兜底：如果传入的 file_path 被 LLM 误填成了 document_id，再次做二次容错解析
    if not real_file_path and file_path and file_path != raw_target:
        real_file_path = resolve_document_file_path(file_path)

    if not real_file_path or not os.path.exists(real_file_path):
        return f"无法定位文档对应的物理磁盘文件: document_id/file_path='{raw_target}'。请确认文档已被正确接收并解析。"

    if not real_file_path.endswith(".docx"):
        return f"当前工具仅支持 Word (.docx) 格式文件的精细样式提取，定位到的目标文件为: {real_file_path}"

    try:
        doc = docx.Document(real_file_path)
        current_chapter = "未分类章节"
        matched_results: List[Dict[str, str]] = []

        def collect_paragraph_matches(paragraph: Paragraph, chapter: str) -> None:
            """收集单个段落中符合样式的 Run。"""
            text = paragraph.text.strip()
            if not text:
                return

            if chapter_keyword and chapter_keyword not in chapter and chapter_keyword not in text:
                return

            for run in paragraph.runs:
                r_text = run.text.strip()
                if r_text and _match_style(run, style_type):
                    matched_results.append({
                        "chapter": chapter,
                        "text": r_text
                    })

        for block in _iter_document_blocks(doc):
            if isinstance(block, Paragraph):
                p = block
                text = p.text.strip()
                if not text:
                    continue

                # 章节标题只从正文段落识别，避免表格中的“第1项”等内容误切换章节。
                style_name = p.style.name.lower() if p.style else ""
                if "heading" in style_name or text.startswith(("第", "附")):
                    current_chapter = text

                collect_paragraph_matches(p, current_chapter)
            else:
                # 表格属于当前位置的章节，逐单元格保留 Run 级字体样式。
                for cell_paragraph in _iter_table_paragraphs(block):
                    collect_paragraph_matches(cell_paragraph, current_chapter)

        if not matched_results:
            chapter_info = f"在章节 [{chapter_keyword}] 中" if chapter_keyword else "在全篇文档中"
            return f"{chapter_info} 未找到样式类型为 [{style_type}] 的文本。"

        formatted_lines = [f"✅ 成功找到样式类型 [{style_type}] 匹配结果（共 {len(matched_results)} 条）："]
        for idx, item in enumerate(matched_results, 1):
            formatted_lines.append(f"{idx}. [{item['chapter']}] {item['text']}")

        return "\n".join(formatted_lines)

    except Exception as e:
        logger.exception(f"样式提取工具执行异常: {str(e)}")
        return f"提取样式文本失败: {str(e)}"
