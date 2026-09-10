"""OpenAPI 路由元数据回归测试。"""

import warnings

from fastapi.routing import APIRoute

from app.main import app


def test_openapi_download_routes_should_have_unique_operation_ids():
    """测试两个原文件下载入口的 OpenAPI 操作 ID 唯一且不产生警告。"""
    previous_schema = app.openapi_schema
    app.openapi_schema = None
    try:
        with warnings.catch_warnings(record=True) as captured_warnings:
            warnings.simplefilter("always")
            schema = app.openapi()

        duplicate_warnings = [
            warning
            for warning in captured_warnings
            if "Duplicate Operation ID" in str(warning.message)
        ]
        assert duplicate_warnings == []

        download_operation_ids = {
            schema["paths"][path]["get"]["operationId"]
            for path in (
                "/api/v1/analysis/download/{task_id}",
                "/api/v1/download/{task_id}",
            )
        }
        assert download_operation_ids == {
            "download_original_file_analysis",
            "download_original_file_global",
        }

        download_routes = [
            route
            for route in app.routes
            if isinstance(route, APIRoute)
            and route.path in {
                "/api/v1/analysis/download/{task_id}",
                "/api/v1/download/{task_id}",
            }
        ]
        assert len(download_routes) == 4
        assert sum("GET" in route.methods for route in download_routes) == 2
        assert sum("HEAD" in route.methods for route in download_routes) == 2
    finally:
        app.openapi_schema = previous_schema
