"""国内模型 API 能力声明与运行时适配规则。"""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ModelCapabilities:
    """描述一个 provider/model 的协议能力，避免在 Agent 中散落字符串判断。"""

    provider: str
    protocol: str = "chat_completions"
    supports_tools: bool = True
    supports_json_output: bool = True
    supports_streaming_tools: bool = True
    supports_native_compaction: bool = False
    preserve_reasoning_fields: bool = False
    context_window: int | None = None
    tokenizer: str = "provider_usage"
    reasoning_policy: str = "visible_only"

    def to_dict(self) -> dict[str, object]:
        """将能力快照转换为可持久化字典。"""
        return asdict(self)


def resolve_model_capabilities(model_name: str | None, base_url: str | None) -> ModelCapabilities:
    """根据模型名和 API 地址解析保守的 provider 能力。"""
    normalized_model = str(model_name or "").lower()
    normalized_base_url = str(base_url or "").lower()

    if "deepseek" in normalized_model or "deepseek" in normalized_base_url:
        return ModelCapabilities(
            provider="deepseek",
            preserve_reasoning_fields=True,
            reasoning_policy="preserve_with_tools",
        )

    if (
        "glm" in normalized_model
        or "bigmodel.cn" in normalized_base_url
        or "z.ai" in normalized_base_url
    ):
        return ModelCapabilities(
            provider="glm",
            preserve_reasoning_fields=True,
            reasoning_policy="clear_or_preserve_explicitly",
        )

    return ModelCapabilities(provider="openai_compatible")
