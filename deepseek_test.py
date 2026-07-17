import httpx
import json
import os
from dotenv import load_dotenv

# 加载同级目录下的 .env 文件
load_dotenv(".env")

api_key = os.getenv("OPENAI_API_KEY")
base_url = os.getenv("OPENAI_API_BASE", "https://api.deepseek.com").rstrip("/")
model_name = os.getenv("LLM_MODEL_NAME", "deepseek-chat")

# 兼容带有 /v1 或没有 /v1 的 base_url
if base_url.endswith("/v1"):
    url = f"{base_url}/chat/completions"
else:
    url = f"{base_url}/chat/completions"

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {api_key}"
}
data = {
    "model": model_name,
    "messages": [{"role": "user", "content": "你好"}]
}

try:
    response = httpx.post(url, headers=headers, json=data, timeout=10.0)
    print("状态码:", response.status_code)
    print("返回内容:", response.text)
    
    if response.status_code == 402:
        print("结论：确实是欠费了！(402 Insufficient Balance)")
    elif response.status_code == 200:
        print("结论：API 正常，并且没有欠费！")
        
except Exception as e:
    print(f"结论：网络根本不通，请求没发出去！错误类型: {type(e).__name__} - {e}")
