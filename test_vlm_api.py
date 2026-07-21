import os
import base64
import json
import httpx
from openai import OpenAI
from dotenv import load_dotenv

# 加载 .env 文件中的环境变量
load_dotenv()

# ======= 模型配置 =======
# 1. 阿里通义千问多模态 (推荐 qwen-vl-plus，成本较低且效果极佳)
ALI_API_BASE = os.getenv("ALI_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1")
ALI_API_KEY = os.getenv("ALI_API_KEY", "")
ALI_MODEL_NAME = os.getenv("ALI_MODEL_NAME", "qwen-vl-plus")

# 2. 原本地部署模型
LOCAL_API_BASE = os.getenv("LOCAL_API_BASE")
LOCAL_API_KEY = os.getenv("LOCAL_API_KEY", "")
LOCAL_MODEL_NAME = os.getenv("LOCAL_MODEL_NAME", "minimax-m3-mxfp8")

# --- 切换使用哪个模型 ---
# 默认使用阿里模型，如果 .env 中 USE_ALI="False" 则使用本地模型
USE_ALI = os.getenv("USE_ALI", "True").lower() == "true"

if USE_ALI:
    API_BASE = ALI_API_BASE
    API_KEY = ALI_API_KEY
    MODEL_NAME = ALI_MODEL_NAME
else:
    API_BASE = LOCAL_API_BASE
    API_KEY = LOCAL_API_KEY
    MODEL_NAME = LOCAL_MODEL_NAME
# =======================
def test_vlm(image_path):
    # "C:\Users\ming\Desktop\承装（修、试）电力设施许可证.png"
    image_path = r"C:\Users\ming\Desktop\建筑业企业资质证书.png"
    if not os.path.exists(image_path):
        print(f"Error: 找不到图片文件 {image_path}")
        return

    print(f"正在读取图片: {image_path}")
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("utf-8")
        
    client = OpenAI(
        base_url=API_BASE,
        api_key=API_KEY,
    )
    
    # 我们期望输出的 JSON 格式
    schema_json = '''
    {
      "qualifications": [
        {
          "name": "证书或资质名称（如：安全生产许可证、营业执照）",
          "company_name": "所属公司名称（如：某某建筑工程有限公司）",
          "level": "资质等级（如：一级、特级）",
          "expiry_date": "到期时间，格式 YYYY-MM-DD"
        }
      ]
    }
    '''

    prompt = f"""请从提供的文档图片中提取关键信息。
该文件中可能包含多个独立的不同资质，请务必找出【所有】独立的资质。
如果是一张许可证（如安全生产许可证、承装电力设施许可证等），也要当做一项资质进行提取。

【强制格式约束】
必须返回严格符合以下 JSON Schema 的纯 JSON 格式：
{schema_json}

[极其重要]
1. 只能输出纯 JSON 数据，绝对不要用 ```json 标签包裹！
2. 确保所有的双引号、括号、逗号等符号完美匹配，不允许出现任何语法错误。
"""

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": prompt
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{img_b64}"
                    }
                }
            ]
        }
    ]
    
    print(f"\n正在向本地模型发送请求...")
    print(f"Base URL: {API_BASE}")
    print(f"Model: {MODEL_NAME}")
    
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            temperature=0.1,
        )
        
        result = response.choices[0].message.content
        print("\n✅ 模型返回结果:")
        print(result)
        
        # 将原始输出写入文件方便您查看
        with open("raw_output.txt", "w", encoding="utf-8") as out_f:
            out_f.write(result)
        print("\n(提示：输出的原文已经保存到当前目录下的 raw_output.txt 文件中，您可以直接打开查看)")
        
        # 尝试解析 JSON 确认格式是否正确
        try:
            # 去除可能包含的 markdown 标签 ```json 和 ```
            clean_result = result.strip()
            if clean_result.startswith("```json"):
                clean_result = clean_result[7:]
            elif clean_result.startswith("```"):
                clean_result = clean_result[3:]
            if clean_result.endswith("```"):
                clean_result = clean_result[:-3]
            clean_result = clean_result.strip()

            parsed = json.loads(clean_result)
            print("\n🎉 JSON 解析成功!")
            print(json.dumps(parsed, indent=2, ensure_ascii=False))
        except json.JSONDecodeError as e:
            print(f"\n❌ JSON 解析失败: {e}")
            
    except Exception as e:
        print(f"\n❌ 请求失败: {e}")

if __name__ == "__main__":
    # 请将此处路径替换为您想要测试的实际图片路径
    test_vlm("test_image.jpg")
