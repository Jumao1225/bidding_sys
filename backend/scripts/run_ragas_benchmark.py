"""
运行开源 Ragas 评估基准测试 CLI 工具
-------------------------------------
使用方式：
  python scripts/run_ragas_benchmark.py --result-id <打分结果ID>
"""

import os
import sys
import json
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import SessionLocal
from app.db.models.bid_score import BidScoreResult
from app.services.ragas_eval_service import ragas_eval_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("RagasBenchmark")

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Ragas 开源基准评估命令行工具")
    parser.add_argument("--result-id", type=str, default="", help="打分结果 ID")
    parser.add_argument("--doc-id", type=str, default="", help="文档 ID (根据文档 ID 自动查最新打分记录)")
    args = parser.parse_args()
    
    db = SessionLocal()
    try:
        result_id = args.result_id
        doc_id = args.doc_id
        
        if not result_id and doc_id:
            latest = (
                db.query(BidScoreResult)
                .filter(BidScoreResult.document_id == doc_id)
                .order_by(BidScoreResult.created_at.desc())
                .first()
            )
            if not latest:
                logger.error(f"❌ 数据库中未找到文档 document_id={doc_id} 的任何历史打分记录！")
                return
            result_id = latest.id
            logger.info(f"🔍 根据 doc-id={doc_id} 找到最新打分记录: {result_id}")
        elif not result_id:
            latest = db.query(BidScoreResult).order_by(BidScoreResult.created_at.desc()).first()
            if not latest:
                logger.error("❌ 数据库中未找到任何历史打分结果！")
                return
            result_id = latest.id
            logger.info(f"🔍 未指定参数，自动获取系统最新打分记录: {result_id}")
            
        summary = ragas_eval_service.evaluate_score_result(db=db, score_result_id=result_id)
        
        print("\n" + "=" * 80)
        print("          Ragas 开源评估指标全面计算结果 (Ragas Benchmark)")
        print("=" * 80)
        print(f"打分记录 ID: {summary['score_result_id']}")
        print(f"关联标书 ID: {summary['document_id']}")
        print(f"评估评分项总数: {summary['total_evaluated_items']}")
        print("-" * 80)
        
        m = summary['overall_metrics']
        print(f"【核心综合 Ragas 评分】: {m['ragas_score'] * 100:.2f} / 100 分")
        print(f"  ├─ 忠实度 / 防幻觉 (Faithfulness)   : {m['faithfulness'] * 100:.2f}%")
        print(f"  ├─ 评语相关度 (Answer Relevance)   : {m['answer_relevance'] * 100:.2f}%")
        print(f"  └─ 上下文召回率 (Context Recall)   : {m['context_recall'] * 100:.2f}%")
        print("-" * 80)
        
        print(f"{'评分项名称':<30} | {'得分/满分':<10} | {'防幻觉分':<10} | {'召回率':<10}")
        print("-" * 80)
        for item in summary['item_details']:
            score_str = f"{item['score']}/{item['max_score']}"
            print(f"{item['item_code']:<30} | {score_str:<10} | {item['faithfulness']*100:6.1f}%    | {item['context_recall']*100:6.1f}%")
        print("=" * 80 + "\n")
        
    finally:
        db.close()

if __name__ == "__main__":
    main()
