"""
RAG 检索召回率 (Retrieval Recall & Hit Rate) 自动化评估工具
--------------------------------------------------
用于自动化测试招投标系统中双轨检索与大章直连机制的召回率 (Recall@K) 与命中率 (Hit Rate)。
"""

import os
import sys
import json
import logging
from typing import List, Dict, Any

# 将 app 加入 PYTHONPATH
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import SessionLocal
from app.db.models.project import DocChunk
from app.agents.tools.bid_scorer_tools import retrieve_bid_content_for_category

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("RAGEval")

# 定制评测标准真值集 (Ground Truth Dataset)
GROUND_TRUTH_DATASET = [
    {
        "case_name": "履约能力分 - 类似业绩与合同扫描件召回",
        "category": "履约能力分",
        "items": [
            {
                "title": "类似业绩",
                "sub_category": "类似业绩",
                "scoring_criteria": "投标人2023年以来的类似业绩介绍（以合同签订时间为准），每有一个得 2 分，最多得 10分。（请在投标文件中提供合同扫描件，不提供的不得分）。"
            }
        ],
        "expected_keywords": ["合同", "工程", "项目"],
        "expected_chunk_indices": [120, 134],
    },
    {
        "case_name": "技术及质量 - 技术参数符合性与证明文件召回",
        "category": "技术及质量保证比较",
        "items": [
            {
                "title": "技术参数符合性情况",
                "sub_category": "技术参数符合性情况",
                "scoring_criteria": "所投设备的技术参数满足或高于招标文件要求的得9分；出现一个负偏离扣1分，扣完为止。各投标人均应提供相关的证明材料（彩页或提供原厂家确认并加盖公章的技术参数表或投标人盖章的技术参数表等能证明技术参数的资..."
            }
        ],
        "expected_keywords": ["技术", "符合性", "逆变器"],
        "expected_chunk_indices": [42, 47, 48],
    },
    {
        "case_name": "方案内容 - 平面布置与施工方案正文召回",
        "category": "方案内容",
        "items": [
            {
                "title": "根据平面布置，产品安装节点做法、深化图纸、节点图、效果图进行评审",
                "sub_category": "平面布置及深化图纸",
                "scoring_criteria": "内容合理、有针对性、符合本项目需求的，得20分..."
            },
            {
                "title": "施工方案说明。包含施工进度计划、工艺流程、质量保证措施进行评分",
                "sub_category": "施工方案说明",
                "scoring_criteria": "方案内容合理、有针对性得10分..."
            }
        ],
        "expected_keywords": ["平面布置", "施工", "节点"],
        "expected_chunk_indices": [50, 51, 72, 73],
    },
    {
        "case_name": "价格分 - 报价表与开标一览表召回",
        "category": "价格分",
        "items": [
            {
                "title": "价格分",
                "sub_category": None,
                "scoring_criteria": "采用低价优先法计算..."
            }
        ],
        "expected_keywords": ["开标", "1072658", "报价"],
        "expected_chunk_indices": [2, 130],
    }
]

def run_rag_eval(doc_id: str):
    """
    针对指定文档 ID 运行 RAG 召回率自动化评估
    """
    logger.info(f"🚀 开始执行 RAG 召回率评估, document_id={doc_id}")
    
    db = SessionLocal()
    try:
        total_chunks = db.query(DocChunk).filter(DocChunk.document_id == doc_id).count()
        if total_chunks == 0:
            logger.error(f"❌ 数据库中未查到 document_id={doc_id} 的切片！请检查 document_id。")
            return
        
        logger.info(f"📊 文档总切片数: {total_chunks}")
        
        results = []
        hit_cases = 0
        total_cases = len(GROUND_TRUTH_DATASET)
        
        for case in GROUND_TRUTH_DATASET:
            c_name = case["case_name"]
            items = case["items"]
            exp_kw = case["expected_keywords"]
            
            # 执行系统的召回
            retrieved_text = retrieve_bid_content_for_category(document_id=doc_id, items=items)
            
            # 计算关键词命中覆盖率 (Keyword Hit Rate)
            hit_kws = [kw for kw in exp_kw if kw in retrieved_text]
            kw_recall = len(hit_kws) / len(exp_kw) if exp_kw else 1.0
            
            is_hit = kw_recall > 0.5
            if is_hit:
                hit_cases += 1
                
            results.append({
                "case_name": c_name,
                "category": case["category"],
                "retrieved_len": len(retrieved_text),
                "kw_recall": kw_recall,
                "hit_keywords": hit_kws,
                "missing_keywords": [kw for kw in exp_kw if kw not in hit_kws],
                "status": "[PASS] 100% 命中" if kw_recall == 1.0 else ("[WARN] 部分命中" if is_hit else "[FAIL] 召回失效")
            })
            
        print("\n" + "=" * 80)
        print(f"       RAG 检索召回率评估报告 (Document ID: {doc_id})")
        print("=" * 80)
        print(f"{'测试用例':<35} | {'返回字数':<8} | {'关键词召回率':<12} | {'评估结果'}")
        print("-" * 80)
        for r in results:
            print(f"{r['case_name']:<35} | {r['retrieved_len']:<10} | {r['kw_recall']*100:6.1f}%     | {r['status']}")
            if r['missing_keywords']:
                print(f"   └─ 缺失关键词: {r['missing_keywords']}")
        print("-" * 80)
        
        overall_hit_rate = (hit_cases / total_cases) * 100
        avg_kw_recall = sum(r['kw_recall'] for r in results) / total_cases * 100
        
        print(f"整体 Case 命中率 (Hit Rate@K): {overall_hit_rate:.1f}% ({hit_cases}/{total_cases})")
        print(f"平均关键词召回率 (Avg Recall@K): {avg_kw_recall:.1f}%")
        print("=" * 80 + "\n")
        
    finally:
        db.close()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="RAG 召回率评测脚本")
    parser.add_argument("--doc-id", type=str, default="d55ae462-a1a5-4048-91a4-c57e3099ea74", help="文档 ID")
    args = parser.parse_args()
    
    run_rag_eval(args.doc_id)
