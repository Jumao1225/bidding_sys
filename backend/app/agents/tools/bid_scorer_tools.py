"""
标书打分工具集 (bid_scorer_tools.py)

封装 BidScorerAgent 核心打分逻辑：
- RAG 批量检索投标文件相关内容
- LLM 结构化打分（单轮）
- 三轮共识计算（取中位数）
- 防幻觉护栏（分值截断、空内容兜底）
"""

import json
import statistics
from typing import List, Dict, Any, Optional
from loguru import logger

from app.services.rag_service import rag_service
from app.services.llm_service import llm_service


# ============================================================
# 1. 多级索引 RAG 检索封装 (章节结构索引 + 语义切片索引)
# ============================================================

def _extract_dynamic_keywords(items: List[Dict[str, Any]]) -> List[str]:
    """
    从评分项列表中动态提取关键搜索词，避免在代码中硬编码固定业务名词。
    
    :param items: 评分项列表
    :return: 动态抓取的关键词列表
    """
    keywords = set()
    for item in items:
        title = str(item.get("title") or "").strip()
        sub_cat = str(item.get("sub_category") or "").strip()
        criteria = str(item.get("scoring_criteria") or "").strip()
        
        # 抓取标题与子类目核心名词
        for text in [title, sub_cat]:
            if text:
                # 去除普通连字符与停用词，提取 2~8 字的核心实体名
                import re
                clean_terms = re.findall(r'[\u4e00-\u9fa5A-Za-z0-9]{2,8}', text)
                for term in clean_terms:
                    if term not in ["评分", "标准", "要求", "分值", "得分", "得分点"]:
                        keywords.add(term)

        # 抓取评分标准中的关键专有名词
        if criteria:
            import re
            terms = re.findall(r'[\u4e00-\u9fa5]{3,8}', criteria[:150])
            for t in terms[:5]:
                if not any(stop in t for stop in ["满意", "较好", "满足", "符合", "提供", "具备", "根据"]):
                    keywords.add(t)

    return [k for k in keywords if len(k) >= 2][:12]


def _clean_markdown_images(text: str) -> str:
    """清理重复的 Markdown 图片链接占位符，避免大量图纸占位符耗尽 RAG 上下文预算"""
    if not text:
        return ""
    import re
    # 将重复的图片 Markdown ![Images/xxx](Images/xxx) 压缩为简短标识
    cleaned = re.sub(r'!\[Images/([^\]]+)\]\(Images/[^)]+\)', r'[图片占位]', text)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned


def retrieve_bid_content_for_category(
    document_id: str,
    items: List[Dict[str, Any]],
    top_k: int = 50,
    max_context_chars: int = 500000,
) -> str:
    """
    多级索引检索 (Multi-Level Index Retrieval)：
    - 一级：章节结构索引 (Chapter Index) — 动态提取关键词，探查 DB 中匹配的大章正文切片
    - 二级：语义切片索引 (Semantic Index) — 基于向量相似度全局搜寻 top_k 切片
    - 上下文预算管理 (Context Budgeting) — 自动去重并控制总字符长度

    :param document_id: 投标文件 Document ID
    :param items: 该 category 下的评分项列表
    :param top_k: 向量检索切片数
    :param max_context_chars: 最大允许输出字符上限
    :return: 格式化后的上下文参考文本
    """
    # 1. 动态生成检索关键词与查询文本
    dynamic_keywords = _extract_dynamic_keywords(items)
    search_queries = []
    for item in items:
        title = item.get("title", "")
        criteria = item.get("scoring_criteria", "")
        sub_cat = item.get("sub_category", "")
        query_parts = [p for p in [title, sub_cat, criteria[:100]] if p]
        search_queries.append(" ".join(query_parts))

    combined_query = " ".join(search_queries)
    logger.info(
        f"🔍 [多级检索] document_id={document_id}, 评分项={len(items)}, "
        f"动态关键词={dynamic_keywords}"
    )

    # 2. 二级检索：语义切片索引 (Semantic Index)
    vector_raw = rag_service.search_bidding_document(
        document_id=document_id,
        query=combined_query,
        top_k=top_k,
        context_mode="chapter",
    )
    vector_content = _clean_markdown_images(vector_raw)

    # 3. 一级检索：章节结构索引 (Chapter Index)
    struct_blocks = []
    seen_contents = set()
    matched_section_titles = set()

    if document_id and dynamic_keywords:
        try:
            from app.db.session import SessionLocal
            from app.db.models.project import DocChunk
            from sqlalchemy import or_

            with SessionLocal() as db:
                conditions = []
                for kw in dynamic_keywords:
                    conditions.append(DocChunk.section_title.ilike(f"%{kw}%"))

                if conditions:
                    matched_chunks = (
                        db.query(DocChunk)
                        .filter(DocChunk.document_id == document_id)
                        .filter(DocChunk.chunk_index > 0)  # 剔除 0 号目录页
                        .filter(or_(*conditions))
                        .order_by(DocChunk.chunk_index)
                        .limit(30)
                        .all()
                    )

                    for c in matched_chunks:
                        c_text = c.content.strip() if c.content else ""
                        c_clean = _clean_markdown_images(c_text)
                        if c_clean and c_clean not in seen_contents and c_clean not in vector_content:
                            seen_contents.add(c_clean)
                            if c.section_title:
                                matched_section_titles.add(c.section_title)
                            header = f"### 【章节结构索引: {c.section_title or '正文'} | 切片 #{c.chunk_index}】\n"
                            struct_blocks.append(header + c_clean)

                    if struct_blocks:
                        logger.info(
                            f"⚡ [章节结构索引] 命中 {len(struct_blocks)} 个目标章节切片! "
                            f"涵盖章节: {list(matched_section_titles)}"
                        )
        except Exception as e:
            logger.warning(f"⚠️ 章节结构索引检索出现非致命异常: {e}")

    # 4. 上下文拼接与预算控制 (Context Budgeting)
    full_parts = []
    if struct_blocks:
        full_parts.append("## 📌 章节结构索引定向直查结果\n" + "\n\n".join(struct_blocks))
    if vector_content:
        full_parts.append("## 🔍 语义切片索引向量检索结果\n" + vector_content)

    final_content = "\n\n".join(full_parts)

    if not final_content or final_content.strip() == "":
        logger.warning(f"⚠️ [多级检索] 未检索到投标文件相关内容, document_id={document_id}")
        return "【未在投标文件中检索到与当前评分维度相关的内容】"

    # 上下文截断保护
    if len(final_content) > max_context_chars:
        final_content = final_content[:max_context_chars] + "\n\n...[由于长度预算限制，后续参考内容已自动截断]"

    logger.info(
        f"✅ [多级检索] 完成, 最终上下文长度={len(final_content)} 字 | "
        f"预览片段: {repr(final_content[:120])}"
    )
    return final_content


# ============================================================
# 2. LLM 单轮打分 (CO-STAR 框架 + 防幻觉黄金标准)
# ============================================================

def _format_items_for_prompt(items: List[Dict[str, Any]]) -> str:
    """
    将评分项列表格式化为 Prompt 中可读的评分细则文本。

    :param items: 评分项列表
    :return: 格式化后的文本
    """
    lines = []
    for idx, item in enumerate(items, 1):
        code = str(item.get("item_code") or item.get("title") or f"第{idx}项").strip()
        title = item.get("title", "未知评分项")
        max_score = item.get("max_score", 0)
        criteria = item.get("scoring_criteria", "无详细标准")
        scoring_type = item.get("scoring_type", "未知")
        rules = item.get("rules_summary", [])

        line = (
            f"### 评分项 [{code}] — {title}\n"
            f"- 满分: {max_score} 分\n"
            f"- 评分类型: {scoring_type}\n"
            f"- 评分标准原文: {criteria}\n"
        )
        if rules:
            line += "- 结构化得分要点:\n"
            for r in rules:
                line += f"  - {r}\n"
        lines.append(line)

    return "\n".join(lines)


def _build_scoring_prompt(
    items: List[Dict[str, Any]],
    bid_content: str,
    round_idx: int,
    category: str,
    user_instruction: Optional[str] = None,
) -> str:
    """
    构建单轮打分的 LLM Prompt，遵循 CO-STAR 框架 + 防幻觉黄金标准。

    :param items: 该 category 下的评分项列表
    :param bid_content: RAG 检索到的投标文件内容
    :param round_idx: 当前轮次索引（0-based）
    :param category: 评分分类名称
    :param user_instruction: 用户自定义微调/重算指导指令
    :return: 完整的 Prompt 字符串
    """
    user_guidance_section = ""
    if user_instruction and user_instruction.strip():
        user_guidance_section = f"""
# 🎯 最高优先级指令：用户微调评审规则 (User Fine-Tuning Guidance)
【评委主任补充指导规则】: {user_instruction.strip()}
- 请务必**优先遵从**上述用户补充规则进行打分评估。
- 如果上述规则指示了特定的评价前提或修正算式（例如：单标书默认其报价为最低有效报价给满分/对符合项直接给满分等），请严格执行上述指令，并在 scoring_basis / deduction_reason 中注明依据该补充指令调整！
"""

    return f"""# 角色 (Context)
你是一位持有注册造价工程师、一级建造师双证的资深评标专家，拥有 15 年政府采购评标经验。
当前正在按照《评标办法》对一份投标文件的【{category}】部分进行 **独立盲审打分**（第 {round_idx + 1} 轮）。
{user_guidance_section}
# 目标 (Objective)
请严格按照下方的【评分细则】，逐项对比【投标文件相关内容】，为每一项给出客观分数、评分依据和具体扣分原因。

# 风格 (Style)
- 评分依据必须**直接引用**投标文件中的原文片段（用「」标注引用），不得凭主观印象
- 扣分原因必须具体到**缺失了什么、不符合哪条标准**
- 禁止使用"整体较好"、"基本满足"等模糊表述

# 基调 (Tone)
严谨、客观、零容忍数字幻觉。宁可少给分，不可多给分。

# 受众 (Audience)
评标委员会主任，需要依据你的打分做出评标决议。

# 🚨 最高指令：防幻觉铁律 (Default to Null)
- 如果投标文件中**完全找不到**与某评分项对应的内容（且未指定冲突的特殊用户微调规则） → 该项强制得 0 分，且 scoring_basis 填“未找到对应文件内容”
- 如果投标文件仅**部分提及**但未达到评分标准 → 按阶梯打分，给出实际匹配的分值
- **严禁**利用你的互联网常识补充投标文件中不存在的信息
- ai_score 绝对不可超过 max_score，也不可为负数

# 【评分细则】（{category}，共 {len(items)} 项）
{_format_items_for_prompt(items)}

# 【投标文件相关内容】（检索结果）
{bid_content}

# 【输出格式】— 必须是纯 JSON 数组，不要包含 markdown 代码块标记
[
  {{
    "item_code": "对应的评分项编号",
    "ai_score": 该项得分（浮点数，0 ≤ ai_score ≤ max_score），
    "confidence": 置信度（0.0~1.0，基于你对评分的确定程度），
    "scoring_basis": "引用投标文件原文的评分依据（用「」标注原文片段）",
    "deduction_reason": "得分/扣分判定理由：若有扣分请说明具体扣分原因；若为满分请结合该项具体响应内容说明满分理由（必须针对具体项目具体描述，切勿使用固定套话）",
    "suggestion": "改进建议，null 表示无需改进"
  }}
]
"""


def llm_score_batch(
    items: List[Dict[str, Any]],
    bid_content: str,
    round_idx: int,
    category: str,
    user_instruction: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    执行单轮 LLM 结构化打分。

    :param items: 该 category 下的评分项列表
    :param bid_content: RAG 检索到的投标文件内容
    :param round_idx: 当前轮次索引
    :param category: 评分分类名称
    :param user_instruction: 用户自定义微调指令
    :return: 解析后的打分结果列表
    """
    prompt = _build_scoring_prompt(
        items=items,
        bid_content=bid_content,
        round_idx=round_idx,
        category=category,
        user_instruction=user_instruction,
    )
    logger.info(
        f"🧠 [LLM] 执行第 {round_idx + 1} 轮打分, "
        f"category={category}, 评分项数={len(items)}"
        f"{f', 微调指令={user_instruction[:30]}' if user_instruction else ''}"
    )

    try:
        # 调用 LLM 生成文本
        result_text = llm_service.generate_text(prompt=prompt, temperature=0.1)

        # 清理 markdown 代码块标记
        cleaned = result_text.strip()
        if cleaned.startswith("```"):
            import re
            cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
            cleaned = re.sub(r'\s*```$', '', cleaned)

        scored_items = json.loads(cleaned)

        # 护栏 L3：分值截断与智能容错匹配
        for idx_scored, scored in enumerate(scored_items):
            item_code_val = str(scored.get("item_code") or "").strip()
            # 查找原始评分项
            original = next(
                (
                    i for i in items
                    if str(i.get("item_code") or "").strip() == item_code_val
                    or str(i.get("title") or "").strip() == item_code_val
                ),
                None,
            )
            if not original and len(items) == 1:
                original = items[0]
            if not original and item_code_val:
                import re
                match_num = re.search(r'\d+', item_code_val)
                if match_num:
                    num_val = int(match_num.group(0)) - 1
                    if 0 <= num_val < len(items):
                        original = items[num_val]
            if not original and 0 <= idx_scored < len(items):
                original = items[idx_scored]

            max_s = float(original.get("max_score") or original.get("score") or 0.0) if original else 0.0
            raw_score = float(scored.get("ai_score") or 0.0)

            if original:
                canonical_code = str(original.get("item_code") or original.get("title") or "").strip()
                scored["item_code"] = canonical_code

            # 强制截断：0 ≤ ai_score ≤ max_score
            scored["ai_score"] = max(0.0, min(raw_score, max_s))
            if raw_score != scored["ai_score"]:
                logger.warning(
                    f"⚡ [护栏L3] 分值截断: {scored.get('item_code')} "
                    f"原始={raw_score} → 截断后={scored['ai_score']} (max={max_s})"
                )

            logger.info(
                f"📝 [LLM第{round_idx+1}轮] [{category}] {scored.get('item_code')}: "
                f"得分={scored['ai_score']}/{max_s} | "
                f"扣分原因={scored.get('deduction_reason') or '无'} | "
                f"依据: {repr(str(scored.get('scoring_basis', ''))[:80])}"
            )

        logger.info(f"✅ [LLM] 第 {round_idx + 1} 轮打分完成, 返回 {len(scored_items)} 项结果")
        return scored_items

    except json.JSONDecodeError as e:
        logger.error(f"❌ [LLM] 第 {round_idx + 1} 轮打分结果 JSON 解析失败: {e}")
        return [
            {
                "item_code": str(item.get("item_code") or item.get("title") or f"unknown_{idx}").strip(),
                "ai_score": 0,
                "confidence": 0.0,
                "scoring_basis": "LLM 返回格式异常，无法解析",
                "deduction_reason": f"打分解析失败: {str(e)}",
                "suggestion": None,
            }
            for idx, item in enumerate(items)
        ]
    except Exception as e:
        logger.exception(f"❌ [LLM] 第 {round_idx + 1} 轮打分异常: {e}")
        return [
            {
                "item_code": str(item.get("item_code") or item.get("title") or f"unknown_{idx}").strip(),
                "ai_score": 0,
                "confidence": 0.0,
                "scoring_basis": f"打分过程异常: {str(e)}",
                "deduction_reason": f"打分异常: {str(e)}",
                "suggestion": None,
            }
            for idx, item in enumerate(items)
        ]


# ============================================================
# 3. 三轮共识计算 (中位数贴合度选优 Median-Proximity Selection)
# ============================================================

def compute_consensus(
    items: List[Dict[str, Any]],
    all_rounds: List[List[Dict[str, Any]]],
    category: str,
) -> List[Dict[str, Any]]:
    """
    对每个评分项取三轮打分的中位数作为最终分数。
    评语与依据提取策略（Median-Proximity Selection）：
    - 选择得分与 median_score 绝对差值最小的轮次结果作为 best_round，
      确保引用依据 (scoring_basis) 与扣分原因 (deduction_reason) 与中位数得分 100% 逻辑对齐。

    :param items: 原始评分项列表
    :param all_rounds: N 轮打分结果列表
    :param category: 评分分类名称
    :return: 共识后的打分结果列表
    """
    logger.info(f"🗳️ [共识] 开始计算三轮共识, category={category}, 评分项数={len(items)}")
    consensus = []

    for item in items:
        code = str(item.get("item_code") or item.get("title") or "").strip()
        max_s = float(item.get("max_score") or item.get("score") or 0.0)
        matched_round_items: List[Dict[str, Any]] = []

        # 匹配各轮结果
        for round_result in all_rounds:
            match = next(
                (r for r in round_result if str(r.get("item_code") or "").strip() == code),
                None,
            )
            if not match and len(round_result) == 1 and len(items) == 1:
                match = round_result[0]
            if match:
                matched_round_items.append(match)

        # 无有效打分结果 → 兜底 0 分
        if not matched_round_items:
            logger.warning(f"⚠️ [共识] {code} 无有效打分结果, 强制 0 分")
            consensus.append({
                "item_code": code,
                "category": category,
                "sub_category": item.get("sub_category"),
                "title": item.get("title", ""),
                "max_score": max_s,
                "ai_score": 0,
                "confidence": 0.0,
                "score_variance": 0.0,
                "all_round_scores": [],
                "scoring_basis": "三轮打分均未返回有效结果",
                "deduction_reason": "无有效打分数据",
                "suggestion": "请检查投标文件是否包含该评分项相关内容",
            })
            continue

        scores = [m.get("ai_score", 0.0) for m in matched_round_items]

        # 1. 计算中位数得分
        sorted_scores = sorted(scores)
        median_score = sorted_scores[len(sorted_scores) // 2]

        # 2. 中位数贴合度选优：挑选其打分最接近 median_score 的轮次作为最佳引用轮次
        best_round = min(
            matched_round_items,
            key=lambda r: (
                abs(r.get("ai_score", 0.0) - median_score),
                -r.get("confidence", 0.0),  # 距离相同时，优先取更高置信度
            ),
        )

        # 3. 计算标准差与一致性置信度
        std_dev = statistics.stdev(scores) if len(scores) > 1 else 0.0
        consistency_confidence = max(0.0, 1.0 - std_dev / max_s) if max_s > 0 else 0.5

        logger.info(
            f"⚖️ [共识对齐] [{category}] {code} ({item.get('title', '')}): "
            f"3轮得分={scores} → 最终中位数={median_score}/{max_s} (标准差={std_dev:.2f}) | "
            f"最佳依据: {repr(str(best_round.get('scoring_basis', ''))[:60])}"
        )

        consensus.append({
            "item_code": code,
            "category": category,
            "sub_category": item.get("sub_category"),
            "title": item.get("title", ""),
            "max_score": max_s,
            "ai_score": median_score,
            "confidence": round(consistency_confidence, 2),
            "score_variance": round(std_dev, 2),
            "all_round_scores": scores,
            "scoring_basis": best_round.get("scoring_basis", ""),
            "deduction_reason": best_round.get("deduction_reason"),
            "suggestion": best_round.get("suggestion"),
        })

    logger.info(
        f"✅ [共识] category={category} 共识计算完成, "
        f"有效项={len(consensus)}/{len(items)}"
    )
    return consensus

