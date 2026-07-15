from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class MinerUSection(BaseModel):
    """
    MinerU 解析出来的单独章节结构
    """
    title: str = Field(..., description="章节标题")
    text: str = Field(..., description="章节纯文本/Markdown内容")
    page_start: Optional[int] = Field(default=1, description="起始页码")
    content_type: str = Field(default="chapter_block", description="元素类别描述")


class MinerUParseResponse(BaseModel):
    """
    MinerU 文件解析响应数据模型
    """
    task_id: str = Field(..., description="解析任务ID")
    file_name: str = Field(..., description="原始文件名")
    parse_mode: str = Field(default="auto", description="解析模式 (auto/txt/ocr)")
    is_mineru_native: bool = Field(default=False, description="是否由 MinerU 原生客户端解析完成")
    md_file_path: str = Field(..., description="导出的绝对路径 .md 文件")
    markdown_content: str = Field(..., description="解析出的全量 Markdown 文本")
    page_count: int = Field(default=1, description="文档总页数或块数")
    sections: List[MinerUSection] = Field(default_factory=list, description="归组后的结构化章节列表")
    images: List[Dict[str, Any]] = Field(default_factory=list, description="提取的图片元数据列表")


class MinerUHealthResponse(BaseModel):
    """
    MinerU 环境服务健康检查响应
    """
    is_installed: bool = Field(..., description="magic-pdf 命令行工具或 SDK 是否可用")
    executable_path: Optional[str] = Field(default=None, description="magic-pdf 可执行文件路径")
    supported_formats: List[str] = Field(default_factory=lambda: ["pdf", "docx", "doc"], description="支持的文件格式列表")
    message: str = Field(..., description="运行环境诊断描述说明")
