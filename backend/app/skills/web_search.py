from langchain_core.tools import tool

@tool
def web_search(query: str) -> str:
    """
    当你需要查询最新的法律法规、或搜索互联网上关于某个公司的公开招投标信息时使用此技能。
    参数 query: 要搜索的关键字或法律法规名称
    """
    # 这里只是一个占位符。实际生产中，可在这里接入 SerpAPI, DuckDuckGo 等互联网搜索引擎。
    print(f"[Skill Execution] 正在全网搜索: {query}")
    return f"模拟搜索结果：关于 '{query}' 的最新法规显示，禁止任何形式的围标串标行为。"
