from unittest.mock import Mock, patch

from app.services.model_connectivity_service import ModelConnectivityService


def _mock_response(status_code: int, payload: object) -> Mock:
    """构造接口探测服务使用的最小 HTTP 响应桩。"""
    response = Mock()
    response.status_code = status_code
    response.json.return_value = payload
    return response


def test_test_llm_model_should_return_available_when_chat_completion_succeeds():
    """主语言模型返回 choices 时应判定接口可用。"""
    response = _mock_response(200, {"choices": [{"message": {"content": "连接成功"}}]})

    with patch(
        "app.services.model_connectivity_service.requests.post",
        return_value=response,
    ) as post_mock:
        result = ModelConnectivityService().test(
            model_type="llm",
            api_key="llm-key",
            api_base="https://llm.example/v1",
            model_name="test-llm",
            tenant_id="tenant-a",
        )

    assert result["available"] is True
    assert result["model_name"] == "test-llm"
    post_mock.assert_called_once()
    assert post_mock.call_args.args[0] == "https://llm.example/v1/chat/completions"
    assert post_mock.call_args.kwargs["json"]["model"] == "test-llm"
    assert post_mock.call_args.kwargs["headers"]["Authorization"] == "Bearer llm-key"


def test_test_vlm_model_should_use_openai_compatible_chat_endpoint():
    """视觉模型应复用兼容 Chat Completions 接口完成文本探测。"""
    response = _mock_response(200, {"choices": [{"message": {"content": "连接成功"}}]})

    with patch("app.services.model_connectivity_service.requests.post", return_value=response) as post_mock:
        result = ModelConnectivityService().test(
            model_type="vlm",
            api_key="vlm-key",
            api_base="https://vlm.example/v1/",
            model_name="test-vlm",
        )

    assert result["available"] is True
    assert post_mock.call_args.args[0] == "https://vlm.example/v1/chat/completions"


def test_test_mineru_model_should_probe_read_only_result_endpoint():
    """MinerU 使用随机任务查询验证鉴权，不应提交新的解析任务。"""
    response = _mock_response(404, {"code": 404, "msg": "batch not found"})

    with patch("app.services.model_connectivity_service.requests.get", return_value=response) as get_mock, patch(
        "app.services.model_connectivity_service.requests.post"
    ) as post_mock:
        result = ModelConnectivityService().test(
            model_type="mineru",
            api_key="mineru-token",
            api_base="https://mineru.example/api/v4",
        )

    assert result["available"] is True
    assert "未创建解析任务" in result["message"]
    assert "/extract-results/batch/" in get_mock.call_args.args[0]
    post_mock.assert_not_called()


def test_test_model_should_return_configuration_message_without_http_call_when_required_value_is_missing():
    """缺少必要配置时应尽早返回，不发起外部网络请求。"""
    with patch("app.services.model_connectivity_service.requests.post") as post_mock:
        result = ModelConnectivityService().test(
            model_type="llm",
            api_key="",
            api_base="https://llm.example/v1",
            model_name="test-llm",
        )

    assert result["available"] is False
    assert "API Key" in result["message"]
    assert result["latency_ms"] == 0
    post_mock.assert_not_called()


def test_test_llm_model_should_return_unavailable_when_upstream_rejects_credentials():
    """上游返回鉴权失败时应给出不可用结果且不泄露响应正文。"""
    response = _mock_response(401, {"error": {"message": "secret detail should not be exposed"}})

    with patch("app.services.model_connectivity_service.requests.post", return_value=response):
        result = ModelConnectivityService().test(
            model_type="llm",
            api_key="bad-key",
            api_base="https://llm.example/v1",
            model_name="test-llm",
        )

    assert result["available"] is False
    assert "API Key 无效" in result["message"]
    assert "secret detail" not in result["message"]
