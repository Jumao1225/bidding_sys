import os
import re
import uuid
import docx
from typing import Dict, Any, Optional, List
from loguru import logger
from pathlib import Path

from app.services.parsers.base_parser import BaseParser

# 1 级大章识别正则模式匹配库
MAJOR_CHAPTER_PATTERNS: List[re.Pattern] = [
    re.compile(r'^\s*[*#]*\s*(第[一二三四五六七八九十百零\d]+[章节部分篇].*)'),
    re.compile(r'^\s*[*#]*\s*(附[件录表][一二三四五六七八九十\dA-Za-z]+.*)'),
]

# 中文汉字序号二级标题识别
ORDINAL_HEADING_PATTERN: re.Pattern = re.compile(r'^[一二三四五六七八九十百]+、')

class DocxParser(BaseParser):
    """
    专门针对 Word (.docx) 的解析器。
    使用 python-docx 原位置交错解析，保障表格不割裂。
    """
    def __init__(self, output_base_dir: Optional[str] = None):
        if output_base_dir:
            self.output_base_dir = Path(output_base_dir)
        else:
            base_dir = Path(__file__).resolve().parent.parent.parent.parent
            self.output_base_dir = base_dir / "uploads" / "docx_output"
        os.makedirs(self.output_base_dir, exist_ok=True)

    @staticmethod
    def _is_table_caption(text: str, paragraph: Any) -> bool:
        if not text or len(text) > 80:
            return False

        if re.match(r'^表\s*[\d一二三四五六七八九十百]+', text):
            return True

        try:
            style_name = paragraph.style.name.lower() if paragraph.style else ""
            if any(kw in style_name for kw in ("caption", "表题", "table caption")):
                return True
        except Exception:
            pass

        if len(text) <= 60:
            try:
                valid_runs = [r for r in paragraph.runs if r.text.strip()]
                if valid_runs and all(r.bold for r in valid_runs):
                    return True
            except Exception:
                pass

        if len(text) <= 60 and (text.endswith("：") or text.endswith(":")):
            return True

        SENTENCE_END_PUNCTUATIONS = ("。", "；", "？", "！", ".", ";", "?", "!")
        if len(text) <= 30 and not any(p in text for p in SENTENCE_END_PUNCTUATIONS):
            return True

        return False

    def _convert_docx_to_markdown(self, docx_path: str) -> str:
        if not os.path.exists(docx_path):
            raise FileNotFoundError(f"未找到指定的 Word 文件: {docx_path}")

        logger.info(f"DocxParser: 开始使用 python-docx 解析文档: {docx_path}")
        doc = docx.Document(docx_path)
        md_lines: List[str] = []

        from docx.text.paragraph import Paragraph
        from docx.table import Table

        body_children = list(doc.element.body)

        for i, child in enumerate(body_children):
            if child.tag.endswith('p'):
                p = Paragraph(child, doc)
                text = p.text.strip()
                if not text:
                    continue

                is_caption = False
                for next_child in body_children[i + 1:]:
                    if next_child.tag.endswith('p'):
                        next_p = Paragraph(next_child, doc)
                        if next_p.text.strip():
                            break
                    elif next_child.tag.endswith('tbl'):
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
                    md_lines.append(f"## {text}\n")
                elif is_caption:
                    md_lines.append(f"\n**{text}**")
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

    def parse(self, file_path: str, task_id: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        current_task_id = task_id or str(uuid.uuid4())
        file_name = os.path.basename(file_path)
        parse_mode = kwargs.get("parse_mode", "auto")

        task_output_dir = self.output_base_dir / current_task_id
        os.makedirs(task_output_dir, exist_ok=True)
        md_file_path = task_output_dir / "output.md"

        try:
            markdown_content = self._convert_docx_to_markdown(file_path)
        except Exception as ex:
            logger.error(f"内置 Word 解析器失败: {str(ex)}")
            raise RuntimeError(f"DocxParser 解析失败: {str(ex)}")

        with open(md_file_path, "w", encoding="utf-8") as f:
            f.write(markdown_content)

        return {
            "task_id": current_task_id,
            "file_name": file_name,
            "parse_mode": parse_mode,
            "is_mineru_native": False,
            "md_file_path": str(md_file_path),
            "markdown_content": markdown_content,
            "page_count": 1
        }

docx_parser = DocxParser()
