import os
import logging
from typing import List, Optional
from langchain_core.documents import Document
import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

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
            pages_to_check = min(check_pages, total_pages)
            
            for i in range(pages_to_check):
                page = doc[i]
                text = page.get_text("text").strip()
                images = page.get_images()
                
                # 如果该页几乎没有文本（如少于20个字符）但包含图片，很有可能是扫描件
                if len(text) < 20 and len(images) > 0:
                    doc.close()
                    return True
                    
            doc.close()
            return False
        except Exception as e:
            logger.error(f"检测 PDF 是否为扫描件时发生错误: {str(e)}")
            return False

    def parse_with_mineru(self, file_path: str) -> List[Document]:
        """
        处理复杂扫描件的后备方案：MinerU
        (TODO: 当前为占位方法，实际需调用 MinerU 服务/命令)
        """
        logger.warning(f"检测到扫描件 {file_path}，当前 MinerU 解析仍为存根 (Stub) 实现。")
        return [
            Document(
                page_content="[扫描件解析存根] 此处应为 MinerU 提取的 Markdown 内容。",
                metadata={"page_num": 1, "section_title": "扫描件", "content_type": "text"}
            )
        ]

    def _convert_doc_to_docx(self, file_path: str) -> str:
        """
        将老旧的 .doc 格式转换为 .docx 格式。
        依赖系统中安装的 LibreOffice (soffice命令) 或 Windows 下的 Word COM 组件。
        如果转换失败，抛出异常。
        返回转换后的 .docx 文件路径。
        """
        import subprocess
        
        docx_path = file_path + "x"
        if os.path.exists(docx_path):
            return docx_path
            
        logger.info(f"正在将 .doc 文件转换为 .docx: {file_path}")
        try:
            # 尝试使用 LibreOffice 进行无头转换 (跨平台推荐方式)
            # 注意：在 Windows 上，soffice 需要加入环境变量，或者指定完整路径
            command = [
                "soffice",
                "--headless",
                "--convert-to", "docx",
                "--outdir", os.path.dirname(file_path),
                file_path
            ]
            
            # 由于可能未配置环境变量，在 Windows 上若 soffice 失败，尝试备用的 win32com
            try:
                subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            except FileNotFoundError:
                logger.warning("未在环境变量中找到 LibreOffice (soffice)，尝试使用 Windows Word COM 组件...")
                # Windows COM fallback
                import win32com.client
                word = win32com.client.Dispatch("Word.Application")
                word.Visible = False
                doc = word.Documents.Open(os.path.abspath(file_path))
                doc.SaveAs2(os.path.abspath(docx_path), FileFormat=16) # 16 = wdFormatXMLDocument
                doc.Close()
                word.Quit()
                
            if not os.path.exists(docx_path):
                raise RuntimeError("转换命令执行成功，但未生成目标 .docx 文件")
                
            logger.info(f"转换成功: {docx_path}")
            return docx_path
        except Exception as e:
            logger.error(f".doc 转 .docx 失败: {str(e)}")
            raise e

    def parse_and_chunk(self, file_path: str, chunk_size: int = 1000, chunk_overlap: int = 200) -> List[Document]:
        """
        核心解析与切片方法：
        1. 检查是否为扫描件，如果是则路由给 MinerU。
        2. 使用 Docling 提取标准 Markdown。
        3. 使用 LangChain 切片器进行语义分块。
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")

        # 1. 扫描件路由
        if self.is_scanned_pdf(file_path):
            logger.info("路由到 MinerU 处理扫描件...")
            return self.parse_with_mineru(file_path)

        # 1.5. 老旧 .doc 格式转换为 .docx
        if file_path.lower().endswith(".doc"):
            file_path = self._convert_doc_to_docx(file_path)

        # 2. Docling 提取
        logger.info(f"使用 Docling 解析文档: {file_path}")
        try:
            converter = self._get_docling_converter()
            conversion_result = converter.convert(file_path)
            
            # 使用 Langchain 的 docling chunker 进行层次化切片
            from docling_core.transforms.chunker.hierarchical_chunker import HierarchicalChunker
            
            chunker = HierarchicalChunker()
            chunks = chunker.chunk(conversion_result.document)
            
            # 将 Docling 的 Chunks 转换为 Langchain 的 Documents
            docs = []
            for chunk in chunks:
                metadata = {
                    "section_title": chunk.meta.headings[0] if chunk.meta.headings else "",
                    "content_type": chunk.meta.doc_items[0].label if chunk.meta.doc_items else "text",
                    "page_num": chunk.meta.doc_items[0].prov[0].page_no if (chunk.meta.doc_items and chunk.meta.doc_items[0].prov) else 1,
                    "source": file_path
                }
                docs.append(Document(page_content=chunk.text, metadata=metadata))
                
            return docs
            
        except Exception as e:
            logger.error(f"Docling 解析失败: {str(e)}")
            raise e

# 单例导出
extractor_service = ExtractorService()
