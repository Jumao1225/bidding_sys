from typing import Dict, Literal

from pydantic import BaseModel, ConfigDict, Field


class ModelConfigUpdate(BaseModel):
    """租户级模型运行配置更新请求。"""

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
    """当前租户生效的模型运行配置。"""

    tenant_id: str = Field(description="配置所属租户ID")
    values: Dict[str, str] = Field(default_factory=dict, description="模型配置键值")


class ModelConnectivityTestRequest(BaseModel):
    """模型连通性测试请求，值来自页面当前草稿而不要求先保存。"""

    model_type: Literal["llm", "mineru", "vlm"] = Field(description="待测试的模型类型")
    api_key: str = Field(default="", max_length=2048, description="模型 API Key 或 MinerU Token")
    api_base: str = Field(default="", max_length=1024, description="模型 API 地址")
    model_name: str = Field(default="", max_length=255, description="模型名称")


class ModelConnectivityTestResponse(BaseModel):
    """模型连通性测试结果。"""

    model_type: Literal["llm", "mineru", "vlm"] = Field(description="测试的模型类型")
    model_name: str | None = Field(default=None, description="测试的模型名称")
    available: bool = Field(description="模型接口是否可用")
    latency_ms: int = Field(ge=0, description="本次探测耗时，单位毫秒")
    message: str = Field(description="面向管理员的测试结果说明")
