from typing import Dict

from pydantic import BaseModel, ConfigDict, Field


class ModelConfigUpdate(BaseModel):
    """平台级模型运行配置更新请求。"""

    model_config = ConfigDict(extra="forbid")

    OPENAI_API_KEY: str = Field(default="", description="招投标文件处理语言模型 API Key")
    OPENAI_API_BASE: str = Field(default="", description="招投标文件处理语言模型 API 地址")
    LLM_MODEL_NAME: str = Field(default="", description="招投标文件处理语言模型名称")
    MINERU_API_TOKEN: str = Field(default="", description="MinerU OCR API Token")
    MINERU_API_BASE_URL: str = Field(default="", description="MinerU OCR API 地址")
    ALI_VLM_API_KEY: str = Field(default="", description="视觉模型 API Key")
    ALI_VLM_API_BASE: str = Field(default="", description="视觉模型 API 地址")
    ALI_VLM_MODEL_NAME: str = Field(default="", description="视觉模型名称")


class ModelConfigResponse(BaseModel):
    """当前生效的模型运行配置。"""

    tenant_id: str = Field(description="配置所属租户ID")
    values: Dict[str, str] = Field(default_factory=dict, description="模型配置键值")
