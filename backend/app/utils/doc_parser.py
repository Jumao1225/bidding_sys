import io
import logging

logger = logging.getLogger(__name__)

class DocumentParser:
    """
    负责解析 Word 招标文件的核心引擎，使用 docling 将文档转换为纯文本供 AI 消费。
    """
    
    @staticmethod
    def extract_text_from_word(file_bytes: bytes, filename: str = "document.docx") -> str:
        """
        从 Word 字节流中提取所有文本
        """
        # 将重量级的 docling 延迟加载，极大加速 FastAPI 启动时间
        from docling.datamodel.base_models import DocumentStream
        from docling.document_converter import DocumentConverter
        
        try:
            buf = io.BytesIO(file_bytes)
            # docling 依赖文件名来推断文档类型
            source = DocumentStream(name=filename, stream=buf)
            converter = DocumentConverter()
            result = converter.convert(source)
            return result.document.export_to_markdown()
        except Exception as e:
            logger.error(f"Word 解析失败: {str(e)}")
            raise RuntimeError(f"无法解析该 Word 文件: {str(e)}")

    @staticmethod
    def extract_tables_from_word(file_bytes: bytes, filename: str = "document.docx") -> list:
        """
        提取表格内容，用于识别物品采购清单 (BOM)
        """
        # docling 也支持提取表格信息，后续可以根据需求深入解析
        return []
