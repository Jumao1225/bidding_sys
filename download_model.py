import os
import sys
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def download_bge_m3():
    try:
        from modelscope.hub.snapshot_download import snapshot_download
    except ImportError:
        logger.error("请先安装 modelscope ")
        sys.exit(1)

    # 获取当前脚本所在目录作为项目根目录
    project_root = os.path.dirname(os.path.abspath(__file__))
    models_dir = os.path.join(project_root, "models")
    target_dir = os.path.join(models_dir, "bge-m3")
    
    os.makedirs(models_dir, exist_ok=True)
    
    logger.info(f"开始从 ModelScope (魔搭社区) 下载 BAAI/bge-m3 模型...")
    logger.info(f"目标保存路径: {target_dir}")
    
    try:
        # 使用 modelscope 的 snapshot_download 
        # local_dir 指定下载到此目录，它会直接下载国内服务器的内容
        snapshot_download(
            model_id="BAAI/bge-m3", # ModelScope 上的 bge-m3 镜像 ID
            local_dir=target_dir
        )
        logger.info(f"✅ 模型下载并完整解压到本地: {target_dir}")
    except Exception as e:
        logger.error(f"❌ 下载过程中出现错误: {e}")

if __name__ == "__main__":
    download_bge_m3()
