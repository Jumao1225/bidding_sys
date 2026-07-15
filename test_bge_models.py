import torch
from transformers import AutoTokenizer, AutoModel

try:
    print("正在加载 Tokenizer 和 Model...")
    # "D:\Myproject\bidding_sys\models\bge-m3"
    model_path = r"D:\Myproject\bidding_sys\models\bge-m3"

    tokenizer = AutoTokenizer.from_pretrained(model_path)
    model = AutoModel.from_pretrained(model_path)
    print("模型加载成功！")

    # 测试推理
    sentences = ["测试模型可用性"]
    encoded_input = tokenizer(sentences, padding=True, truncation=True, return_tensors='pt')

    # 运行推理 (PyTorch Transformer 标准推理)
    with torch.no_grad():
        model_output = model(**encoded_input)
        # BGE 默认取 [CLS] 标记的输出作为句向量
        sentence_embeddings = model_output[0][:, 0]
        
    print("\n--- 验证结果 ---")
    print(f"向量生成成功，维度: {sentence_embeddings.shape} (预期为 (1, 1024))")
    print(f"前5维数值 (检查非NaN): {sentence_embeddings[0][:5].tolist()}")
    print("模型完全可用！")

except Exception as e:
    print("\n模型验证失败，错误信息如下：")
    print(str(e))