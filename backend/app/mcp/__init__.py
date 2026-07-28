"""
MCP (Model Context Protocol) 协议服务与客户端适配层模块
"""

from app.mcp.office_cli_server import mcp_server, run_mcp_server
from app.mcp.office_cli_client import office_cli_mcp_client, get_office_cli_mcp_tools

__all__ = [
    "mcp_server",
    "run_mcp_server",
    "office_cli_mcp_client",
    "get_office_cli_mcp_tools"
]
