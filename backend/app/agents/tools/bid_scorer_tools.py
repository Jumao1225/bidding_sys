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

def _extract_dynamic_keywords(items: List[Dict[str, Any]], tenant_id: Optional[str] = None) -> List[str]:
    """
    使用大模型 (LLM) 智能分析评分维度，预测并重写出在【投标文件】中可能出现的
    核心章节标题、服务专有名词及高精准度检索关键词，彻底替代规则抽取。
    
    :param items: 评分项列表
    :return: LLM 生成的精准检索关键词与预测章节列表
    """
    if not items:
        return []

    # 汇总评分维度上下文
    items_desc = []
    for idx, item in enumerate(items, 1):
        title = item.get("title", "")
        sub_cat = item.get("sub_category", "")
        criteria = item.get("scoring_criteria", "")
        items_desc.append(f"评分项 {idx}:\n- 标题: {title}\n- 子分类: {sub_cat}\n- 评分细则: {criteria[:200]}")

    joined_desc = "\n\n".join(items_desc)

    prompt = f"""你是一位招投标领域的检索与评测专家。请分析以下【招标文件】的评分维度项，预测并重写出在【投标文件】中最可能对应的核心章节标题、技术/服务专有名词以及精准检索关键词。

{joined_desc}

【要求】
1. 预测投标文件中的可能章节路径或标题（如: "第四章 服务响应方案情况", "服务团队配置", "售后服务响应时间保障", "现场到达时间"）。
2. 提取最具有业务针对性的专有名词实体（5 ~ 12 个）。
3. 严格禁止输出“评分、标准、要求、满足、符合”等通用废词。
4. 必须输出合法 JSON 对象，包含 "keywords" 字段，格式如：
{{"keywords": ["第四章 服务响应方案情况", "服务团队配置", "售后服务响应时间保障", "现场问题解决", "到达现场承诺"]}}
"""

    try:
        from app.services.llm_service import llm_service
        res_json = llm_service.generate_structured_json(prompt, temperature=0.2, tenant_id=tenant_id)
        if isinstance(res_json, dict) and "keywords" in res_json and isinstance(res_json["keywords"], list):
            llm_keywords = [str(k).strip() for k in res_json["keywords"] if str(k).strip() and len(str(k).strip()) >= 2]
            if llm_keywords:
                logger.info(f"🤖 [LLM 智能检索词扩展] 成功生成 {len(llm_keywords)} 个专业检索词: {llm_keywords}")
                return llm_keywords[:15]
    except Exception as e:
        logger.warning(f"⚠️ [LLM 智能检索词生成失败，启动降级]: {e}")

    # 降级兜底保护（保证 API 异常时不卡死系统）
    fallback_words = set()
    for item in items:
        t = item.get("title", "")
        sc = item.get("sub_category", "")
        for term in [t, sc]:
            if term:
                import re
                for m in re.findall(r'[\u4e00-\u9fa5A-Za-z0-9]{2,8}', term):
                    if m not in ["评分", "标准", "要求", "分值"]:
                        fallback_words.add(m)
    return list(fallback_words)[:10]


def get_bid_document_outline(document_id: str) -> List[str]:
    """获取投标文件的所有真实章节大纲路径列表 (例如: '七、设计方案、服务方案 > 第四章 服务响应方案情况')"""
    if not document_id:
        return []
    try:
        from app.db.session import SessionLocal
        from app.db.models.project import DocChunk

        with SessionLocal() as db:
            chunks = db.query(DocChunk.section_title).filter(
                DocChunk.document_id == document_id,
                DocChunk.chunk_index > 0
            ).distinct().all()

            titles = []
            for (st,) in chunks:
                if st and st != "无章节/正文" and st != "正文" and st not in titles:
                    titles.append(st)
            return titles
    except Exception as e:
        logger.warning(f"⚠️ [目录大纲提取] 异常: {e}")
        return []


def subagent_select_target_chapters(
    category: str,
    subagent_type: str,
    items: List[Dict[str, Any]],
    document_outline: List[str],
    tenant_id: Optional[str] = None,
) -> List[str]:
    """
    专项子 Agent 自主决策：对比自身负责的评分标准与投标文件的实际目录树，
    从目录大纲中自主挑选最可能包含证据正文的目标章节。
    """
    if not document_outline or not items:
        return []

    outline_str = "\n".join([f"- {t}" for t in document_outline])
    items_str = "\n".join([
        f"评分项 {idx+1}: {i.get('title')}\n  分类: {i.get('sub_category')}\n  细则: {i.get('scoring_criteria')[:150]}"
        for idx, i in enumerate(items)
    ])

    prompt = f"""你是一位专业招投标评估子 Agent [{subagent_type}]，负责评估维度【{category}】。

【投标文件的实际目录大纲 (TOC Outline)】:
{outline_str}

【你负责评估的评分标准项】:
{items_str}

请根据你的评估评分标准，对照投标文件的实际目录大纲，自主挑选并决策：上述目录中哪些章节最可能包含本分类评分所需的具体方案正文？

【决策规则】
1. 从【投标文件的实际目录大纲】中挑选完全一致或最相关的章节名称。
2. 可以挑选 1 ~ 6 个最相关的章节。
3. 必须输出合法 JSON，格式为：
{{"selected_chapters": ["挑选的章节1", "挑选的章节2"]}}
"""

    try:
        from app.services.llm_service import llm_service
        res = llm_service.generate_structured_json(prompt, temperature=0.1, tenant_id=tenant_id)
        if isinstance(res, dict) and "selected_chapters" in res and isinstance(res["selected_chapters"], list):
            selected = []
            for c in res["selected_chapters"]:
                c_str = str(c).strip()
                # 寻找目录中的准确匹配或包含项
                matched = [t for t in document_outline if c_str in t or t in c_str]
                if matched:
                    selected.extend(matched)
                elif c_str in document_outline:
                    selected.append(c_str)
            # 去重
            dedup_selected = list(dict.fromkeys(selected))
            if dedup_selected:
                logger.info(f"🧠 [{subagent_type}] 子 Agent 针对 category=[{category}] 自主决策锁定目标章节: {dedup_selected}")
                return dedup_selected
    except Exception as e:
        logger.warning(f"⚠️ [{subagent_type}] 自主决策挑选目标章节失败，启动降级: {e}")

    return []


def _clean_markdown_images(text: str) -> str:
    """清理重复的 Markdown 图片链接占位符，避免大量图纸占位符耗尽 RAG 上下文预算"""
    if not text:
        return ""
    import re
    cleaned = re.sub(r'!\[Images/([^\]]+)\]\(Images/[^)]+\)', r'[图片占位]', text)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned


def retrieve_bid_content_for_category(
    document_id: str,
    items: List[Dict[str, Any]],
    top_k: int = 50,
    max_context_chars: int = 500000,
    category: str = "通用分类",
    tenant_id: Optional[str] = None,
    subagent_type: str = "general_subagent",
) -> str:
    """
    子 Agent 自主目录探查 + 多级索引 RAG 检索：
    1. 提取投标文件的真实 TOC 目录树大纲 (doc_outline)
    2. 子 Agent 结合自身负责的评分标准，从 TOC 大纲中自主挑选定位目标章节
    3. 在 PostgreSQL 中对子 Agent 选定的目标章节执行【全章闭环盲拉】
    4. 融合【语义向量索引】辅助召回全局零星条款
    """
    # 1. 提取投标文件的实际目录大纲并由子 Agent 自主决策目标章节
    doc_outline = get_bid_document_outline(document_id)
    subagent_selected_chapters = subagent_select_target_chapters(
        category=category,
        subagent_type=subagent_type,
        items=items,
        document_outline=doc_outline,
        tenant_id=tenant_id,
    )

    # 2. 动态生成补充关键词与向量查询文本
    dynamic_keywords = _extract_dynamic_keywords(items, tenant_id=tenant_id)
    search_queries = []
    for item in items:
        title = item.get("title", "")
        criteria = item.get("scoring_criteria", "")
        sub_cat = item.get("sub_category", "")
        query_parts = [p for p in [title, sub_cat, criteria[:100]] if p]
        search_queries.append(" ".join(query_parts))

    combined_query = " ".join(search_queries)
    logger.info(
        f"🔍 [子Agent自主检索] category=[{category}], document_id={document_id}, "
        f"目录大纲数={len(doc_outline)}, 自主锁定章节={subagent_selected_chapters}"
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
                    k_str = kw.strip()
                    if len(k_str) >= 2:
                        conditions.append(DocChunk.section_title.ilike(f"%{k_str}%"))
                        conditions.append(DocChunk.content.ilike(f"%{k_str}%"))

                if conditions:
                    # 1. 查找初步命中的种子切片
                    seed_chunks = (
                        db.query(DocChunk)
                        .filter(DocChunk.document_id == document_id)
                        .filter(DocChunk.chunk_index > 0)  # 剔除 0 号目录页
                        .filter(or_(*conditions))
                        .order_by(DocChunk.chunk_index)
                        .limit(20)
                        .all()
                    )

                    # 2. 从种子切片与子 Agent 自主选定的目标章节提取“章节前缀家族”
                    family_prefixes = set(subagent_selected_chapters or [])
                    for c in seed_chunks:
                        st = c.section_title or ""
                        parts = [p.strip() for p in st.split(">") if p.strip()]
                        if len(parts) >= 2:
                            family_prefixes.add(" > ".join(parts[:2]))
                        elif len(parts) == 1:
                            family_prefixes.add(parts[0])

                    # 3. 针对章节前缀家族，执行【全章闭环盲拉】，拉取该大章下的全量连续子节点切片！
                    matched_chunks = []
                    if family_prefixes:
                        family_conditions = [DocChunk.section_title.ilike(f"{pref}%") for pref in family_prefixes]
                        family_chunks = (
                            db.query(DocChunk)
                            .filter(DocChunk.document_id == document_id)
                            .filter(DocChunk.chunk_index > 0)
                            .filter(or_(*family_conditions))
                            .order_by(DocChunk.chunk_index)
                            .limit(100)
                            .all()
                        )
                        matched_chunks.extend(family_chunks)

                    # 兜底补充种子切片
                    seen_ids = {c.id for c in matched_chunks}
                    for c in seed_chunks:
                        if c.id not in seen_ids:
                            matched_chunks.append(c)

                    for c in matched_chunks:
                        c_text = c.content.strip() if c.content else ""
                        c_clean = _clean_markdown_images(c_text)
                        if len(c_clean.strip()) < 5:
                            continue
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
        f"✅ [多级检索] 完成, 最终上下文长度={len(final_content)} 字\n"
        f"==================== [RAG 检索给 LLM 的上下文详情 BEGIN] ====================\n"
        f"{final_content}\n"
        f"==================== [RAG 检索给 LLM 的上下文详情 END] ===================="
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
    tenant_id: Optional[str] = None,
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
        result_text = llm_service.generate_text(prompt=prompt, temperature=0.1, tenant_id=tenant_id)

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


# ============================================================
# Agentic Active RAG 自主反思追问与动态上下文补齐逻辑
# ============================================================

def extract_missing_keywords_from_round(round_result: List[Dict[str, Any]]) -> List[str]:
    """
    从第 1 轮评估结果的 deduction_reason / suggestion 中提取出形如
    “缺少日常运行管理”、“未提供施工工艺流程”、“未包含故障应急处置” 等动态缺失关键词。
    """
    missing_keywords = []
    import re
    patterns = [
        r"(?:缺少|未包含|未提供|未找到|未查到|未见|未列出|部分缺失|不包含)\s*([“「『]?[\u4e00-\u9fa5A-Za-z0-9\s、，和及与]{2,30}[”」』]?)",
        r"(?:针对|补充)\s*([“「『]?[\u4e00-\u9fa5A-Za-z0-9\s、，和及与]{2,30}[”」』]?)",
    ]
    for item in round_result:
        ai_score = item.get("ai_score", 0.0)
        max_score = item.get("max_score", 0.0)
        if max_score > 0 and ai_score < max_score:
            text = (str(item.get("deduction_reason") or "") + " " + str(item.get("suggestion") or "")).strip()
            for pat in patterns:
                matches = re.findall(pat, text)
                for m in matches:
                    clean_str = m.strip("“「『”」』 ").strip()
                    sub_kws = re.split(r'[、，,\s和及与]+', clean_str)
                    for kw in sub_kws:
                        kw_clean = kw.strip()
                        if len(kw_clean) >= 2 and kw_clean not in missing_keywords and kw_clean not in ["内容", "细节", "方案", "条款", "要求", "具体", "判定", "部分", "缺失"]:
                            missing_keywords.append(kw_clean)
    return missing_keywords


def active_refine_context_with_keywords(
    document_id: str,
    bid_content: str,
    missing_keywords: List[str],
) -> str:
    """
    拿着 Agentic 追问提取出的 missing_keywords，去数据库中执行二次定向反查，
    并将新抓取的文本动态去重合并入 bid_content。
    """
    if not document_id or not missing_keywords:
        return bid_content

    logger.info(f"🕵️‍♂️ [Agentic Active RAG] 触发自主二次反查, 缺失追问词={missing_keywords}")
    
    try:
        from app.db.session import SessionLocal
        from app.db.models.project import DocChunk
        from sqlalchemy import or_

        with SessionLocal() as db:
            conditions = []
            for kw in missing_keywords:
                k_str = kw.strip()
                if len(k_str) >= 2:
                    conditions.append(DocChunk.section_title.ilike(f"%{k_str}%"))
                    conditions.append(DocChunk.content.ilike(f"%{k_str}%"))

            if not conditions:
                return bid_content

            extra_chunks = (
                db.query(DocChunk)
                .filter(DocChunk.document_id == document_id)
                .filter(DocChunk.chunk_index > 0)
                .filter(or_(*conditions))
                .order_by(DocChunk.chunk_index)
                .limit(20)
                .all()
            )

            new_blocks = []
            for c in extra_chunks:
                c_text = c.content.strip() if c.content else ""
                c_clean = _clean_markdown_images(c_text)
                if c_clean and c_clean not in bid_content:
                    header = f"### 【Agentic 自主追问二次补全: {c.section_title or '正文'} | 切片 #{c.chunk_index}】\n"
                    new_blocks.append(header + c_clean)

            if new_blocks:
                logger.info(f"⚡ [Agentic Active RAG] 自主反查成功补充 {len(new_blocks)} 个缺失正文切片!")
                appended_text = "\n\n## 📌 Agentic 智能体自主追问补全上下文\n" + "\n\n".join(new_blocks)
                return bid_content + "\n\n" + appended_text
    except Exception as e:
        logger.warning(f"⚠️ [Agentic Active RAG] 二次反查出现非致命异常: {e}")

    return bid_content
