"""控制台日志过滤器单元测试。"""

from app.core.logger import console_log_filter


def _build_log_record(message: str) -> dict[str, str]:
    """构造 Loguru 过滤器所需的最小日志记录。"""
    return {"message": message}


def test_console_log_filter_successful_cost_update_noise_should_hide() -> None:
    """正常场景：BOM 成本保存和层级汇总的重复例行日志应从控制台隐藏。"""
    messages = [
        "BOM 使用稳定父节点关系：legacy_14_低压电缆终端 -> legacy_0_一",
        "成功更新文档 doc-1 的 BOM 成本测算，共 273 项，总额: ¥0.0",
        "👉 请求开始 | PUT | /api/v1/analysis/doc-1/cost-analysis | Client: 127.0.0.1",
        "👈 请求结束 | PUT | /api/v1/analysis/doc-1/cost-analysis | Status: 200 | Time: 0.1830s",
        '127.0.0.1:12345 - "PUT /api/v1/analysis/doc-1/cost-analysis HTTP/1.1" 200',
    ]

    assert all(not console_log_filter(_build_log_record(message)) for message in messages)


def test_console_log_filter_cost_update_error_should_keep() -> None:
    """异常场景：成本保存返回 500 时，错误日志必须继续显示。"""
    message = "👈 请求结束 | PUT | /api/v1/analysis/doc-1/cost-analysis | Status: 500 | Time: 0.1830s"

    assert console_log_filter(_build_log_record(message)) is True


def test_console_log_filter_slow_or_unrelated_log_should_keep() -> None:
    """边界场景：慢请求和无关接口日志不能被误过滤。"""
    slow_message = "👈 请求结束 | PUT | /api/v1/analysis/doc-1/cost-analysis | Status: 200 | Time: 1.2000s 🐌 (慢请求)"
    unrelated_message = "👈 请求结束 | GET | /api/v1/documents | Status: 200 | Time: 0.0200s"

    assert console_log_filter(_build_log_record(slow_message)) is True
    assert console_log_filter(_build_log_record(unrelated_message)) is True


def test_console_log_filter_stable_parent_relation_should_hide() -> None:
    """边界场景：不同节点的稳定父节点关系日志都应从控制台隐藏。"""
    messages = [
        "BOM 使用稳定父节点关系：legacy_1_1 -> legacy_0_一",
        "BOM 使用稳定父节点关系：item-2 -> item-1",
    ]

    assert all(not console_log_filter(_build_log_record(message)) for message in messages)


def test_console_log_filter_unrelated_debug_log_should_keep() -> None:
    """边界场景：其他 DEBUG 日志不能被误过滤。"""
    message = "BOM 层级汇总完成，共处理 273 个项目"

    assert console_log_filter(_build_log_record(message)) is True
