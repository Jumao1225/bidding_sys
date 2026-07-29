import json
import urllib.request
import os


API_KEY = os.getenv("OPENAI_API_KEY", "xq-prod-x62q6N62y02rGzn2101sjdkf2jb3t4b838sd")
API_URL = os.getenv("OPENAI_API_BASE", "http://221.224.69.13:8083/v1/chat/completions")
MODEL_NAME = os.getenv("LLM_MODEL_NAME", "Qwen3.6-27B")

payload = {
    "model": MODEL_NAME,
    "messages": [
        {
            "role": "user",
            "content": "你好，请用一句话证明你已经成功启动并可以正常工作。",
        }
    ],
    "temperature": 0.7,
}

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {API_KEY}",
}

req = urllib.request.Request(
    API_URL, data=json.dumps(payload).encode("utf-8"), headers=headers
)

try:
    print(f"正在尝试连接 {API_URL} ...")
    with urllib.request.urlopen(req, timeout=30) as response:
        result = json.loads(response.read().decode("utf-8"))
        content = result["choices"][0]["message"]["content"]
        print("\n✅ 测试成功！模型返回内容如下：")
        print("-" * 40)
        print(content)
        print("-" * 40)
except Exception as e:
    print(f"\n❌ 连接失败: {e}")