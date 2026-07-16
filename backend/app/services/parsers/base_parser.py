from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

class BaseParser(ABC):
    """
    文档解析器抽象基类
    """
    @abstractmethod
    def parse(self, file_path: str, task_id: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """
        核心解析接口
        返回统一的字典结构：
        {
            "task_id": "...",
            "file_name": "...",
            "parse_mode": "...",
            "is_mineru_native": bool,
            "md_file_path": "...",
            "markdown_content": "...",
            "page_count": int,
            "sections": [] # 可选
        }
        """
        pass
