import os
import uuid
from typing import Dict, Any, Optional
from loguru import logger
from pathlib import Path

from app.services.parsers.base_parser import BaseParser

class DoclingParser(BaseParser):
    """
    基于 IBM Docling 的备用解析器。
    当 MinerU 未配置或 PDF 解析需要轻量级后备方案时使用。
    """
    def __init__(self, output_base_dir: Optional[str] = None):
        if output_base_dir:
            self.output_base_dir = Path(output_base_dir)
        else:
            base_dir = Path(__file__).resolve().parent.parent.parent.parent
            self.output_base_dir = base_dir / "uploads" / "docling_output"
        os.makedirs(self.output_base_dir, exist_ok=True)
        self._docling_converter = None

    def _get_docling_converter(self):
        """懒加载 Docling Converter"""
        if self._docling_converter is None:
            from docling.document_converter import DocumentConverter
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
            
            pipeline_options = PdfPipelineOptions()
            pipeline_options.do_table_structure = True
            pipeline_options.table_structure_options.mode = TableFormerMode.ACCURATE
            
            self._docling_converter = DocumentConverter(
                allowed_formats=[InputFormat.PDF, InputFormat.DOCX]
            )
        return self._docling_converter

    def parse(self, file_path: str, task_id: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")

        current_task_id = task_id or str(uuid.uuid4())
        file_name = os.path.basename(file_path)
        parse_mode = kwargs.get("parse_mode", "auto")

        task_output_dir = self.output_base_dir / current_task_id
        os.makedirs(task_output_dir, exist_ok=True)
        md_file_path = task_output_dir / "output.md"

        logger.info(f"DoclingParser: 启动 Docling 引擎解析文档: {file_path}")
        
        try:
            converter = self._get_docling_converter()
            conversion_result = converter.convert(file_path)
            
            markdown_content = conversion_result.document.export_to_markdown()
            
            if not markdown_content or not markdown_content.strip():
                raise RuntimeError("Docling 导出的 Markdown 为空")
                
            # 保存用于 debug 和原始呈现
            with open(md_file_path, "w", encoding="utf-8") as f:
                f.write(markdown_content)
                
            return {
                "task_id": current_task_id,
                "file_name": file_name,
                "parse_mode": parse_mode,
                "is_mineru_native": False,
                "md_file_path": str(md_file_path),
                "markdown_content": markdown_content,
                "page_count": 1 # Docling 这里导出纯文本后暂时无法精准对应页码
            }
        except Exception as e:
            logger.error(f"Docling 解析失败: {str(e)}")
            raise RuntimeError(f"DoclingParser 解析失败: {str(e)}")

docling_parser = DoclingParser()
