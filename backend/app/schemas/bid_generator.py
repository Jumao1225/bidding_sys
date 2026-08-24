"""
标书撰写与格式提取 Pydantic 数据模型定义。

遵循统一架构规范，所有类与字段必须补充全面的中文类型提示与注释。
"""

from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator


class ContentTypeEnum(str, Enum):
    """
    投标文件格式内容类型枚举
    """
    FORM_TABLE = "form_table"        # 表单与表格样张
    TABLE_TEMPLATE = "table_template"# 表格模板 (兼容别名)
    TEXT_TEMPLATE = "text_template"  # 文本/公文模板 (如授权书、承诺函)
    CHECKLIST = "checklist"          # 审查清单或目录项
    OTHER = "other"                  # 其他格式附件


class BidFormatSection(BaseModel):
    """
    单个投标文件格式/附件格式描述模型
    """
    section_title: str = Field(
        ..., 
        description="格式附件名称，例如：附件一 投标函、附件二 法定代表人授权书"
    )
    content_type: ContentTypeEnum = Field(
        default=ContentTypeEnum.TEXT_TEMPLATE, 
        description="格式内容类型"
    )
    body_markdown: str = Field(
        default="", 
        description="该格式的文本或表格 Markdown 内容"
    )
    placeholders: List[str] = Field(
        default_factory=list, 
        description="该格式中提取出的需填写占位符字段列表，例如：['投标人名称', '法定代表人姓名', '投标总价']"
    )

    @field_validator("section_title", mode="before")
    @classmethod
    def validate_section_title(cls, v: Any) -> str:
        if not v or not str(v).strip():
            return "格式附件"
        return str(v).strip()

    @field_validator("content_type", mode="before")
    @classmethod
    def validate_content_type(cls, v: Any) -> ContentTypeEnum:
        if isinstance(v, ContentTypeEnum):
            return v
        if isinstance(v, str):
            v_lower = v.strip().lower()
            if v_lower in ("form_table", "table_template", "table", "form", "excel", "sheet", "matrix"):
                return ContentTypeEnum.FORM_TABLE
            elif v_lower in ("text_template", "text", "doc", "document", "template", "letter", "statement"):
                return ContentTypeEnum.TEXT_TEMPLATE
            elif v_lower in ("checklist", "list", "check_list", "catalog"):
                return ContentTypeEnum.CHECKLIST
            elif v_lower in ("other", "attachment", "unknown"):
                return ContentTypeEnum.OTHER
            # 尝试直接匹配已有枚举值
            for member in ContentTypeEnum:
                if member.value == v_lower or member.name.lower() == v_lower:
                    return member
            return ContentTypeEnum.OTHER
        return ContentTypeEnum.OTHER

    @field_validator("body_markdown", mode="before")
    @classmethod
    def validate_body_markdown(cls, v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, str):
            return v
        if isinstance(v, (dict, list)):
            import json
            try:
                return json.dumps(v, ensure_ascii=False, indent=2)
            except Exception:
                return str(v)
        return str(v)

    @field_validator("placeholders", mode="before")
    @classmethod
    def validate_placeholders(cls, v: Any) -> List[str]:
        if v is None:
            return []
        if isinstance(v, str):
            return [v.strip()] if v.strip() else []
        if isinstance(v, list):
            return [str(item).strip() for item in v if item is not None and str(item).strip()]
        return []


class BidFormatStructure(BaseModel):
    """
    投标文件格式全量结构化模型
    """
    document_title: str = Field(
        default="投标文件格式模板", 
        description="提取出的标书或格式总标题"
    )
    source_chapter_name: str = Field(
        default="第六章 投标文件格式", 
        description="定位到的源章节名称"
    )
    sections: List[BidFormatSection] = Field(
        default_factory=list, 
        description="提取出的所有格式附件子项列表"
    )
    extraction_mode: str = Field(
        default="native_docx", 
        description="提取模式：native_docx (原生 Word 切片) 或 llm_rebuilt (LLM 重建)"
    )

    @field_validator("sections", mode="before")
    @classmethod
    def validate_sections(cls, v: Any) -> Any:
        if v is None:
            return []
        if isinstance(v, dict):
            return list(v.values())
        if not isinstance(v, list):
            return [v]
        return v


class BidFormatExtractResponse(BaseModel):
    """
    投标文件格式提取 API 返回结果模型
    """
    document_id: str = Field(..., description="相关联的招标文件文档 ID")
    filename: str = Field(..., description="生成的 Word 文件名")
    extracted_sections_count: int = Field(default=0, description="提取出的格式子项总数")
    extraction_mode: str = Field(default="native_docx", description="提取模式")
    download_url: Optional[str] = Field(None, description=" Word 文件的在线下载或预览相对路径")
