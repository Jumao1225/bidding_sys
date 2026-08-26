"""
标书打分 Agent (BidScorerAgent) — 三层架构智能推理中枢

架构模式：1 个 Supervisor 主控 Agent + N 个 专项子 Agent (Supervisor-Specialist Architecture)
节点拓扑：
supervisor_load_node 
   └─► Send() × N 专项子 Agent ➔ specialist_score_node (并行打分)
          └─► supervisor_aggregate_node (汇算校验)
                 └─► supervisor_report_node (总结落库) ➔ END

核心特性：
- 模块 3 智能推理层中枢：Supervisor 进行总体维度拆解与分发
- 专项子 Agent (Specialist Sub-Agents) 并行针对技术参数、方案评估、资质/商务进行结构化探查与三轮共识打分
- 五重护栏：数据源锁定 ➔ 多级索引 RAG ➔ 分值截断 ➔ 中位数贴合共识 ➔ 数学一致性校验
"""

import operator
from typing import TypedDict, List, Dict, Any, Optional, Annotated

from langgraph.graph import StateGraph, END
from langgraph.types import Send
from loguru import logger

from app.agents.tools.bid_scorer_tools import (
    retrieve_bid_content_for_category,
    llm_score_batch,
    compute_consensus,
    extract_missing_keywords_from_round,
    active_refine_context_with_keywords,
)


# ============================================================
# State 定义
# ============================================================

class BidScorerState(TypedDict):
    """BidScorerAgent 的全局状态 (Supervisor State)"""
    # --- 输入参数 ---
    document_id: str             # 被评分的投标文件 Document ID
    source_doc_id: str           # 招标文件 Document ID（评分维度来源）
    user_id: str
    tenant_id: str
    scoring_rounds: int          # 共识轮数

    # --- supervisor_load_node 产出 ---
    score_tree: List[dict]       # 从 DB 加载的完整评分维度树
    weight_distribution: dict    # 权重分布
    evaluation_method: str       # 评标方法名称
    total_possible: float        # 满分值
    categories: List[str]        # 去重后的一级分类列表
    specialist_tasks: Dict[str, str] # 分类到专项子 Agent 类型的映射字典

    # --- specialist_score_node 并发产出 ---
    # Annotated[list, operator.add] 实现 fan-in 自动合并
    scored_items: Annotated[list, operator.add]

    # --- 当前处理的分类（由 Send 注入） ---
    current_category: str
    subagent_type: str           # 专项 Agent 标志 (tech_param, plan_eval, commercial 等)

    # --- supervisor_aggregate_node 产出 ---
    total_score: float
    score_rate: float
    category_scores: Dict[str, dict]
    validation_warnings: List[str]

    # --- supervisor_report_node 产出 ---
    summary: str
    top_improvements: List[dict]
    result_id: str

    # --- 状态控制 ---
    status: str
    error: str


# ============================================================
# Supervisor Node ① — supervisor_load_node (纯 DB 读取 + 领域拆解)
# ============================================================

def _classify_specialist_agent_type(category_name: str) -> str:
    """
    根据分类名称智能路由分配给对应的专项子 Agent 领域。

    :param category_name: 分类名称
    :return: 专项子 Agent 标志 (tech_param / plan_eval / commercial / general)
    """
    cat = category_name.strip()
    if any(k in cat for k in ["技术参数", "参数", "符合性", "规格", "指标"]):
        return "tech_param_subagent"
    elif any(k in cat for k in ["施工方案", "方案", "实施", "布置", "响应", "维护", "服务"]):
        return "plan_eval_subagent"
    elif any(k in cat for k in ["商务", "资质", "业绩", "报价", "价格", "财务", "人员"]):
        return "commercial_subagent"
    return "general_subagent"


def supervisor_load_node(state: BidScorerState) -> dict:
    """
    Supervisor 加载节点：从数据库加载评分维度树并拆解分发任务给专项 Agent。

    职责:
    1. 安全读取 evaluation_metadata 表提取评分维度
    2. 验证 score_tree 非空且被评分标书切片完备
    3. 将不同 category 分配映射至专项子 Agent 任务组
    """
    logger.info("📍 [Supervisor Node 1/4] supervisor_load_node: 加载并拆解评分维度...")

    source_doc_id = state.get("source_doc_id", "")
    document_id = state.get("document_id", "")
    tenant_id = state.get("tenant_id", "")

    if not source_doc_id or not document_id:
        logger.error("❌ 缺少 document_id 或 source_doc_id")
        return {"status": "failed", "error": "缺少必要的文档 ID 参数"}

    from app.db.session import SessionLocal
    from app.db.models.metadata import EvaluationMetadata
    from app.db.models.project import DocChunk
    from sqlalchemy import func

    try:
        with SessionLocal() as db:
            eval_meta = db.query(EvaluationMetadata).filter(
                EvaluationMetadata.document_id == source_doc_id,
                EvaluationMetadata.tenant_id == tenant_id,
            ).first()

            if not eval_meta:
                logger.error(f"❌ 未找到 evaluation_metadata, source_doc_id={source_doc_id}")
                return {"status": "failed", "error": "招标文件尚未完成评分维度提取"}

            score_tree = eval_meta.score_tree
            if not score_tree:
                logger.error("❌ score_tree 为空")
                return {"status": "failed", "error": "评分维度树为空，请先重新提取评分信息"}

            # 校验并归一化评分项编号与满分
            for idx, item in enumerate(score_tree, 1):
                raw_code = item.get("item_code")
                if not raw_code or str(raw_code).strip().lower() in ("none", "null", ""):
                    title_val = str(item.get("title") or item.get("category") or "").strip()
                    item["item_code"] = title_val if (title_val and len(title_val) <= 60) else f"ITEM_{idx:02d}"
                if "max_score" not in item or item.get("max_score") is None:
                    item["max_score"] = float(item.get("score") or item.get("max_val") or 0.0)

            # 验证切片数据
            chunk_count = db.query(func.count(DocChunk.id)).filter(
                DocChunk.document_id == document_id,
                DocChunk.tenant_id == tenant_id,
            ).scalar()

            if not chunk_count or chunk_count == 0:
                logger.error(f"❌ 投标文件无 doc_chunks, document_id={document_id}")
                return {"status": "failed", "error": "投标文件尚未完成向量化解析"}

            # 去重提取分类并分配给专项 Agent 任务组
            categories = list(set(item.get("category", "通用分") for item in score_tree))
            specialist_tasks = {cat: _classify_specialist_agent_type(cat) for cat in categories}

            total_possible = eval_meta.total_score or 100.0
            weight_distribution = eval_meta.weight_distribution or {}
            evaluation_method = eval_meta.evaluation_method or "综合评分法"

            logger.info(
                f"✅ [supervisor_load_node] 加载完成: "
                f"评分项={len(score_tree)}, 拆解分类={categories}, "
                f"专项Agent分配={specialist_tasks}, 满分={total_possible}"
            )

            return {
                "score_tree": score_tree,
                "weight_distribution": weight_distribution,
                "evaluation_method": evaluation_method,
                "total_possible": total_possible,
                "categories": categories,
                "specialist_tasks": specialist_tasks,
                "status": "loaded",
            }

    except Exception as e:
        logger.exception(f"❌ [supervisor_load_node] 异常: {e}")
        return {"status": "failed", "error": f"加载评分维度失败: {str(e)}"}


# ============================================================
# Node ② — specialist_score_node (专项子 Agent 评分引擎)
# ============================================================

def specialist_score_node(state: BidScorerState) -> dict:
    """
    专项子 Agent 节点：由 Supervisor 派发处理特定类目的 RAG 多级检索 + LLM 结构化打分 + 多轮中位数共识。

    通过 LangGraph Send() API 并行分发，每个专项任务独享独立计算链。
    """
    category = state.get("current_category", "未知分类")
    subagent_type = state.get("subagent_type", "general_subagent")
    document_id = state.get("document_id", "")
    score_tree = state.get("score_tree", [])
    scoring_rounds = state.get("scoring_rounds", 3)
    tenant_id = state.get("tenant_id")

    logger.info(
        f"📍 [Specialist Node 2/4] [{subagent_type}] 开始评分 category=[{category}]..."
    )

    items = [i for i in score_tree if i.get("category", "通用分") == category]
    if not items:
        logger.warning(f"⚠️ [{subagent_type}] category=[{category}] 无评分项，跳过")
        return {"scored_items": []}

    logger.info(
        f"   📋 [{subagent_type}] 负责 {len(items)} 个评分项, 共识轮数={scoring_rounds}"
    )

    # 1. 多级索引与子 Agent 自主目录探查 RAG 检索
    bid_content = retrieve_bid_content_for_category(
        document_id=document_id,
        items=items,
        category=category,
        subagent_type=subagent_type,
        tenant_id=tenant_id,
    )

    # 2. Agentic Active RAG 多轮结构化打分与自主反思追问
    all_rounds = []
    
    # 第 1 轮：初审评估
    r1_result = llm_score_batch(
        items=items,
        bid_content=bid_content,
        round_idx=0,
        category=category,
        tenant_id=tenant_id,
    )
    all_rounds.append(r1_result)

    # 自主反思护栏：检查第 1 轮扣分项中是否有“缺少/未包含某些细节”
    missing_kws = extract_missing_keywords_from_round(r1_result)
    if missing_kws and document_id:
        logger.info(f"💡 [{subagent_type}] 第 1 轮初审发现缺项反思关键词: {missing_kws}，启动 Agentic 动态上下文补全...")
        bid_content = active_refine_context_with_keywords(
            document_id=document_id,
            bid_content=bid_content,
            missing_keywords=missing_kws,
            tenant_id=tenant_id,
        )

    # 第 2~N 轮：基于（可能已扩充）的最新上下文执行终审评估
    for round_idx in range(1, scoring_rounds):
        round_result = llm_score_batch(
            items=items,
            bid_content=bid_content,
            round_idx=round_idx,
            category=category,
            tenant_id=tenant_id,
        )
        all_rounds.append(round_result)

    # 3. 三轮共识与中位数贴合度选优
    consensus_items = compute_consensus(
        items=items,
        all_rounds=all_rounds,
        category=category,
    )

    logger.info(
        f"✅ [{subagent_type}] category=[{category}] 打分完成, 共识项={len(consensus_items)}"
    )
    return {"scored_items": consensus_items}


# ============================================================
# Supervisor Node ③ — supervisor_aggregate_node (结果汇算与护栏)
# ============================================================

def supervisor_aggregate_node(state: BidScorerState) -> dict:
    """
    Supervisor 汇算节点：聚合所有专项子 Agent 的打分结果，进行数学校验与护栏限制。

    职责:
    1. 按 category 汇总全量打分
    2. 计算总分 total_score 与得分率 score_rate
    3. 执行分值截断（护栏 L5）与产生告警通知
    """
    logger.info("📍 [Supervisor Node 3/4] supervisor_aggregate_node: 汇总与校验打分...")

    scored_items = state.get("scored_items", [])
    total_possible = state.get("total_possible", 100.0)

    if not scored_items:
        logger.warning("⚠️ [supervisor_aggregate_node] 无有效打分结果")
        return {
            "total_score": 0.0,
            "score_rate": 0.0,
            "category_scores": {},
            "validation_warnings": ["所有评分项均无有效打分结果"],
        }

    category_scores: Dict[str, dict] = {}
    for item in scored_items:
        cat = item.get("category", "通用分")
        if cat not in category_scores:
            category_scores[cat] = {"score": 0.0, "max_total": 0.0, "count": 0}
        category_scores[cat]["score"] += item.get("ai_score", 0.0)
        category_scores[cat]["max_total"] += item.get("max_score", 0.0)
        category_scores[cat]["count"] += 1

    warnings = []
    for cat, cs in category_scores.items():
        if cs["score"] == 0 and cs["max_total"] > 0:
            warnings.append(
                f"⚠️ [{cat}] 所有评分项得 0 分，请检查投标文件是否缺失该部分内容"
            )
        if cs["score"] > cs["max_total"]:
            warnings.append(
                f"❌ [{cat}] 得分 {cs['score']} 超过满分 {cs['max_total']}，自动修饰截断"
            )
            cs["score"] = cs["max_total"]
            logger.warning(f"⚡ [护栏L5] [{cat}] 分数强制截断至满分 {cs['max_total']}")

    total_score = sum(cs["score"] for cs in category_scores.values())
    if total_score > total_possible:
        warnings.append(
            f"❌ 总分 {total_score} 超过满分 {total_possible}，已修饰截断"
        )
        total_score = total_possible

    score_rate = total_score / total_possible if total_possible > 0 else 0.0

    logger.info(
        f"✅ [supervisor_aggregate_node] 汇算完成: "
        f"总分={round(total_score, 2)}/{total_possible}, "
        f"得分率={round(score_rate * 100, 1)}%, 告警数={len(warnings)}"
    )

    return {
        "total_score": round(total_score, 2),
        "score_rate": round(score_rate, 4),
        "category_scores": category_scores,
        "validation_warnings": warnings,
    }


# ============================================================
# Supervisor Node ④ — supervisor_report_node (报告生成与落库)
# ============================================================

def _gap_to_priority(gap: float) -> int:
    """根据失分幅度计算优先级等级（1~5）"""
    if gap >= 10:
        return 5
    elif gap >= 5:
        return 4
    elif gap >= 3:
        return 3
    elif gap >= 1:
        return 2
    return 1


def _build_summary_prompt(state: BidScorerState) -> str:
    """构建 Supervisor 报告的 LLM Prompt"""
    category_scores = state.get("category_scores", {})
    total_score = state.get("total_score", 0)
    total_possible = state.get("total_possible", 100)
    score_rate = state.get("score_rate", 0)
    warnings = state.get("validation_warnings", [])

    category_lines = [
        f"- {cat}: {cs['score']}/{cs['max_total']} ({cs['count']} 项)"
        for cat, cs in category_scores.items()
    ]
    warnings_text = "\n".join(warnings) if warnings else "无告警"

    return f"""你是一位资深评标委员会主任。请基于以下各专项子 Agent 汇算的打分结果，撰写总体评价报告（200~400字）。

# 打分汇总
- 总分: {total_score}/{total_possible}
- 得分率: {round(score_rate * 100, 1)}%
- 各大类得分:
{chr(10).join(category_lines)}

# 校验告警
{warnings_text}

# 要求
1. 给出总体评价级别（优/良/中/差）
2. 总结技术与商务各大模块的核心优势与短板
3. 给出 2~3 条最高优先级的修改提分建议
4. 末尾统一标注："⚠️ 本评分由 AI 模拟评标专家系统生成，仅供投标自检参考"
"""


def supervisor_report_node(state: BidScorerState) -> dict:
    """
    Supervisor 报告节点：生成自然语言报告并持久化落库。
    """
    logger.info("📍 [Supervisor Node 4/4] supervisor_report_node: 生成报告并落库...")

    if state.get("status") == "failed":
        error_msg = state.get("error", "未知错误")
        logger.error(f"❌ [supervisor_report_node] 前置失败: {error_msg}")
        return {
            "summary": f"打分失败: {error_msg}",
            "top_improvements": [],
            "result_id": "",
            "status": "failed",
        }

    scored_items = state.get("scored_items", [])
    total_score = state.get("total_score", 0)

    # 1. 改进建议按失分倒序排序
    improvements = []
    for item in scored_items:
        gap = item.get("max_score", 0) - item.get("ai_score", 0)
        if gap > 0 and item.get("suggestion"):
            improvements.append({
                "priority": _gap_to_priority(gap),
                "category": item.get("category", ""),
                "title": item.get("title", ""),
                "current_score": item.get("ai_score", 0),
                "potential_gain": round(gap, 2),
                "action": item.get("suggestion", ""),
            })
    improvements.sort(key=lambda x: x["potential_gain"], reverse=True)

    # 2. LLM 生成总评摘要
    summary = ""
    try:
        from app.services.llm_service import llm_service
        summary = llm_service.generate_text(
            prompt=_build_summary_prompt(state),
            temperature=0.3,
            tenant_id=state.get("tenant_id"),
        )
        logger.info(f"✅ [supervisor_report_node] 报告生成完成 ({len(summary)} 字)")
    except Exception as e:
        logger.exception(f"❌ [supervisor_report_node] 生成总结失败: {e}")
        summary = f"AI 模拟评分总分: {total_score}/{state.get('total_possible', 100)} (生成异常: {str(e)})"

    # 3. 持久化落库
    result_id = ""
    try:
        result_id = _save_to_db(state, summary, improvements)
        logger.info(f"✅ [supervisor_report_node] 打分落库成功, result_id={result_id}")
    except Exception as e:
        logger.exception(f"❌ [supervisor_report_node] 落库失败: {e}")

    return {
        "summary": summary,
        "top_improvements": improvements[:10],
        "result_id": result_id,
        "status": "completed",
    }


def _save_to_db(
    state: BidScorerState,
    summary: str,
    improvements: List[dict],
) -> str:
    """持久化打分结果与明细数据"""
    from app.db.session import SessionLocal
    from app.db.crud.bid_score import bid_score_crud
    from app.services.llm_service import llm_service

    tenant_id = state.get("tenant_id")
    score_llm = llm_service.get_llm(temperature=0.3, json_mode=False, tenant_id=tenant_id)
    model_name = getattr(score_llm, "model_name", "unknown") if score_llm else "unknown"

    with SessionLocal() as db:
        try:
            result = bid_score_crud.create_score_result(
                db=db,
                tenant_id=state.get("tenant_id", ""),
                user_id=state.get("user_id", ""),
                result_data={
                    "document_id": state.get("document_id", ""),
                    "source_doc_id": state.get("source_doc_id", ""),
                    "evaluation_method": state.get("evaluation_method", ""),
                    "total_score": state.get("total_score", 0),
                    "max_possible": state.get("total_possible", 100),
                    "score_rate": state.get("score_rate", 0),
                    "category_scores": state.get("category_scores", {}),
                    "summary": summary,
                    "top_improvements": improvements[:10],
                    "validation_warnings": state.get("validation_warnings", []),
                    "scoring_rounds": state.get("scoring_rounds", 3),
                    "model_name": model_name,
                },
            )

            items_data = []
            for item in state.get("scored_items", []):
                items_data.append({
                    "item_code": item.get("item_code"),
                    "category": item.get("category", ""),
                    "sub_category": item.get("sub_category"),
                    "title": item.get("title", ""),
                    "max_score": item.get("max_score", 0),
                    "ai_score": item.get("ai_score", 0),
                    "confidence": item.get("confidence", 0),
                    "score_variance": item.get("score_variance", 0),
                    "all_round_scores": item.get("all_round_scores", []),
                    "scoring_basis": item.get("scoring_basis", ""),
                    "deduction_reason": item.get("deduction_reason"),
                    "suggestion": item.get("suggestion"),
                })

            if items_data:
                bid_score_crud.create_score_items_batch(
                    db=db,
                    tenant_id=state.get("tenant_id", ""),
                    user_id=state.get("user_id", ""),
                    score_result_id=result.id,
                    items_data=items_data,
                )

            db.commit()
            logger.info(f"✅ [DB] 数据提交完成: result_id={result.id}, 项数={len(items_data)}")
            return result.id
        except Exception as e:
            db.rollback()
            logger.exception(f"❌ [DB] 提交异常: {e}")
            raise


# ============================================================
# Map-Reduce 路由与 Supervisor 图构建
# ============================================================

def route_to_specialist_subagents(state: BidScorerState) -> list:
    """Supervisor 动态任务派发路由"""
    if state.get("status") == "failed":
        logger.warning("⚠️ [Supervisor 路由] 加载失败，直通 supervisor_report_node")
        return [Send("supervisor_report_node", state)]

    categories = state.get("categories", [])
    specialist_tasks = state.get("specialist_tasks", {})

    logger.info(f"🚀 [Supervisor 路由] 派发 {len(categories)} 个分类到专项子 Agent...")

    sends = []
    for cat in categories:
        sub_type = specialist_tasks.get(cat, "general_subagent")
        sends.append(Send(
            "specialist_score_node",
            {**state, "current_category": cat, "subagent_type": sub_type},
        ))
    return sends


def build_bid_scorer_graph():
    """构建 Supervisor-Specialist Map-Reduce 状态图"""
    workflow = StateGraph(BidScorerState)

    # 注册 4 个核心节点
    workflow.add_node("supervisor_load_node", supervisor_load_node)
    workflow.add_node("specialist_score_node", specialist_score_node)
    workflow.add_node("supervisor_aggregate_node", supervisor_aggregate_node)
    workflow.add_node("supervisor_report_node", supervisor_report_node)

    # 设置入口节点
    workflow.set_entry_point("supervisor_load_node")

    # 条件分支：Supervisor 拆解后派发致专项子 Agent 并行执行
    workflow.add_conditional_edges(
        "supervisor_load_node",
        route_to_specialist_subagents,
        ["specialist_score_node", "supervisor_report_node"],
    )

    # Fan-in 合并致 Supervisor 汇算节点
    workflow.add_edge("specialist_score_node", "supervisor_aggregate_node")

    # 线性流转至报告生成落库
    workflow.add_edge("supervisor_aggregate_node", "supervisor_report_node")
    workflow.add_edge("supervisor_report_node", END)

    return workflow.compile()


# 全局单例
bid_scorer_graph = build_bid_scorer_graph()
