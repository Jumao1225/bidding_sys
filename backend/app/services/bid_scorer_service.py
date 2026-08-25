"""
标书打分业务服务层 (bid_scorer_service.py)

职责:
1. 轻量上传编排：投标文件的 parse + chunk + embedding
2. 打分编排：调用 BidScorerAgent 的 Map-Reduce 状态图
3. 查询编排：组装打分结果返回给 API 层
"""

import os
import hashlib
from typing import Dict, Any, Optional, List

from sqlalchemy.orm import Session
from loguru import logger

from app.db.models.project import Project, Document, DocChunk
from app.db.models.metadata import EvaluationMetadata
from app.db.crud.bid_score import bid_score_crud
from app.services.extractor_service import extractor_service
from app.services.llm_service import llm_service


class BidScorerService:
    """标书打分业务服务"""

    # ============================================================
    # 1. 轻量上传编排（parse + chunk + embedding）
    # ============================================================

    def upload_and_parse_bid(
        self,
        db: Session,
        file_path: str,
        filename: str,
        source_doc_id: str,
        user_id: str,
        tenant_id: str,
    ) -> Dict[str, Any]:
        """
        上传投标文件并执行轻量解析（只做 parse + chunk + embedding）。

        :param db: 数据库会话
        :param file_path: 已保存的文件磁盘路径
        :param filename: 原始文件名
        :param source_doc_id: 关联的招标文件 Document ID
        :param user_id: 用户 ID
        :param tenant_id: 租户 ID
        :return: {"document_id": str, "chunk_count": int, "parse_status": str}
        :raises ValueError: 前置条件不满足时抛出
        """
        logger.info(
            f"📤 [BidScorerService] 轻量上传开始: "
            f"filename={filename}, source_doc_id={source_doc_id}"
        )

        # 1. 验证 source_doc_id 的 evaluation_metadata 存在且 score_tree 非空
        # 以唯一的 UUID (source_doc_id) 为准查询对应的评分分析字典，兼容存量历史和缺省租户记录
        eval_meta = db.query(EvaluationMetadata).filter(
            EvaluationMetadata.document_id == source_doc_id,
        ).first()

        if not eval_meta:
            logger.warning(f"⚠️ 无法找到对应的评标维度解析结果: source_doc_id={source_doc_id}")
            raise ValueError("关联的招标文件尚未完成分析，请先上传并分析招标文件")

        if not eval_meta.score_tree:
            raise ValueError("关联的招标文件尚未提取评分维度，请先完成评分信息提取")

        # 2. 获取或创建 Project
        project = db.query(Project).filter(
            Project.name == "Frontend Uploads",
            Project.tenant_id == tenant_id,
        ).first()
        if not project:
            project = Project(
                tenant_id=tenant_id,
                name="Frontend Uploads",
                status="created",
            )
            db.add(project)
            db.flush()

        # 3. 计算文件哈希用于去重
        file_hash = self._compute_file_hash(file_path)

        # 检查是否有同名同内容的已完成解析记录
        existing_doc = self._find_existing_parsed_doc(
            db, project.id, filename, file_hash
        )
        if existing_doc:
            logger.info(f"♻️ 命中缓存: 同名同内容文件已解析完成, doc_id={existing_doc.id}")
            chunk_count = db.query(DocChunk).filter(
                DocChunk.document_id == existing_doc.id
            ).count()
            return {
                "document_id": existing_doc.id,
                "chunk_count": chunk_count,
                "parse_status": "completed",
                "source_doc_id": source_doc_id,
                "cached": True,
            }

        # 4. 创建 Document 记录
        doc = Document(
            tenant_id=tenant_id,
            user_id=user_id,
            project_id=project.id,
            filename=filename,
            file_path=file_path,
            parse_status="parsing",
            parsed_metadata={
                "doc_type": "bid",
                "source_doc_id": source_doc_id,
                "file_hash": file_hash,
            },
        )
        db.add(doc)
        db.flush()
        logger.info(f"📄 Document 记录已创建, doc_id={doc.id}")

        # 5. 解析 + 切片（针对投标文件启用专属的细颗粒度切分与长表头保护逻辑）
        logger.info(f"🔬 开始解析投标文件 (策略: bid专属分块): {file_path}")
        chunks = extractor_service.parse_and_chunk(file_path, doc_type="bid")
        if not chunks:
            doc.parse_status = "failed"
            db.commit()
            raise ValueError("投标文件解析未获得任何切片，请检查文件格式")

        logger.info(f"✅ 解析完成, 共 {len(chunks)} 个切片")

        # 6. 生成 Embedding（复用 llm_service）
        texts_to_embed = [chunk.page_content for chunk in chunks]
        logger.info(f"🧮 开始生成 Embedding 向量，共 {len(texts_to_embed)} 个切片...")
        embeddings = llm_service.generate_embeddings(texts_to_embed, batch_size=32)
        logger.info(f"✅ Embedding 向量生成完成 (共 {len(embeddings)} 条)")

        # 7. 批量写入 doc_chunks 表
        db_chunks = []
        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            db_chunk = DocChunk(
                tenant_id=tenant_id,
                user_id=user_id or doc.user_id,
                document_id=doc.id,
                content=chunk.page_content,
                chunk_index=chunk.metadata.get("chunk_index", i),
                page_num=chunk.metadata.get("page_num"),
                section_title=chunk.metadata.get("section_path") or chunk.metadata.get("section_title"),
                content_type=chunk.metadata.get("content_type"),
                trace_info=chunk.metadata.get("trace_info"),
                embedding=embedding,
            )
            db_chunks.append(db_chunk)

        db.add_all(db_chunks)
        doc.parse_status = "completed"
        db.commit()

        logger.info(
            f"✅ [BidScorerService] 轻量上传完成: "
            f"doc_id={doc.id}, chunk_count={len(db_chunks)}"
        )

        return {
            "document_id": doc.id,
            "chunk_count": len(db_chunks),
            "parse_status": "completed",
            "source_doc_id": source_doc_id,
            "cached": False,
        }

    # ============================================================
    # 2. 打分编排
    # ============================================================

    def score_bid(
        self,
        document_id: str,
        source_doc_id: str,
        user_id: str,
        tenant_id: str,
        scoring_rounds: int = 3,
    ) -> Dict[str, Any]:
        """
        触发 BidScorerAgent 的 Map-Reduce 打分流程。

        :param document_id: 被评分的投标文件 ID
        :param source_doc_id: 评分维度来源的招标文件 ID
        :param user_id: 用户 ID
        :param tenant_id: 租户 ID
        :param scoring_rounds: 共识轮数
        :return: 打分结果字典
        """
        logger.info(
            f"🎯 [BidScorerService] 启动打分: "
            f"document_id={document_id}, source_doc_id={source_doc_id}, "
            f"scoring_rounds={scoring_rounds}"
        )

        from app.agents.bid_scorer_agent import bid_scorer_graph

        # 构建初始状态
        initial_state = {
            "document_id": document_id,
            "source_doc_id": source_doc_id,
            "user_id": user_id,
            "tenant_id": tenant_id,
            "scoring_rounds": scoring_rounds,
            # 以下字段由各节点填充
            "score_tree": [],
            "weight_distribution": {},
            "evaluation_method": "",
            "total_possible": 100.0,
            "categories": [],
            "scored_items": [],
            "current_category": "",
            "total_score": 0,
            "score_rate": 0,
            "category_scores": {},
            "validation_warnings": [],
            "summary": "",
            "top_improvements": [],
            "result_id": "",
            "status": "",
            "error": "",
        }

        # 执行 LangGraph 状态图
        final_state = bid_scorer_graph.invoke(initial_state)

        logger.info(
            f"✅ [BidScorerService] 打分完成: "
            f"status={final_state.get('status')}, "
            f"total_score={final_state.get('total_score')}/{final_state.get('total_possible')}"
        )

        return {
            "id": final_state.get("result_id", ""),
            "result_id": final_state.get("result_id", ""),
            "document_id": document_id,
            "source_doc_id": source_doc_id,
            "total_score": final_state.get("total_score", 0),
            "max_possible": final_state.get("total_possible", 100),
            "score_rate": final_state.get("score_rate", 0),
            "category_scores": final_state.get("category_scores", {}),
            "summary": final_state.get("summary", ""),
            "top_improvements": final_state.get("top_improvements", []),
            "validation_warnings": final_state.get("validation_warnings", []),
            "status": final_state.get("status", ""),
            "error": final_state.get("error", ""),
        }

    def _generate_rescore_expert_summary(
        self,
        category: str,
        user_instruction: str,
        new_total_score: float,
        max_possible: float,
        score_rate: float,
        cat_scores: Dict[str, Any],
        top_improvements: List[Dict[str, Any]],
        tenant_id: Optional[str] = None,
    ) -> str:
        """使用 LLM 或专业模版合成连贯、流利的专家总体评价报告 (Overall Evaluation Report)"""
        try:
            from app.services.llm_service import llm_service
            cat_details = ", ".join([f"【{c}】{info['score']}/{info['max_total']}分" for c, info in cat_scores.items()])
            imp_details = "；".join([f"{imp['title']}(建议可提升+{imp['potential_gain']}分)" for imp in top_improvements[:2]])

            prompt = f"""你是一位资深评标委员会主任。请基于以下最新的打分数据，撰写一段专业、流利、连贯的总体评分报告（150~250字）。

# 最新打分数据
- 汇算总分: {new_total_score} / {max_possible} 分（得分率: {round(score_rate * 100, 1)}%）
- 各大类得分分布: {cat_details}
- 最近评委微调指令: 针对【{category}】维度，执行了评委指示：“{user_instruction}”
- 主要扣分短板: {imp_details if imp_details else '无明显扣分项，整体响应质量优秀'}

# 要求
1. 以评标委员会主任的口吻，对本次投标文件的整体表现给出定性评价（优/良/中/差）
2. 总结商务与技术各大模块的整体响应质量，阐述结合评委微调指示后的打分变化
3. 指出当前主要的提分短板并给出专家建议
4. 末尾统一附带说明："⚠️ 本打分已结合评委微调规则实时刷新，仅供投标决策参考。"
5. 直接输出自然语言报告正文，不要包含任何 markdown 标题或多余的引导词。
"""
            response = llm_service.generate_text(prompt=prompt, temperature=0.3, tenant_id=tenant_id)
            if response and len(response.strip()) > 30:
                return response.strip()
        except Exception as e:
            logger.warning(f"⚠️ [Rescore] 生成 LLM 专家摘要异常，使用备用专业总结模版: {e}")

        # 高质量备用专业专家总结模版
        grade = "优秀" if score_rate >= 0.85 else ("良好" if score_rate >= 0.70 else "中等")
        cats_str = "；".join([f"【{c}】{info['score']}/{info['max_total']}分" for c, info in cat_scores.items()])
        return (
            f"本项目投标文件综合评价等级为【{grade}】，结合评委微调指示，最新汇算总分为 {new_total_score}/{max_possible} 分（得分率 {round(score_rate * 100, 1)}%）。\n"
            f"各大类响应得分分布为：{cats_str}。\n"
            f"经评估，投标文件在【{category}】等核心章节做出了积极响应。建议针对剩余扣分项补充完善佐证材料与技术方案编制细节，以进一步提升投标竞争力。\n\n"
            f"⚠️ 本打分已结合评委微调规则实时刷新，仅供投标决策参考。"
        )


    def rescore_category_with_instruction(
        self,
        db: Session,
        result_id: str,
        category: str,
        user_instruction: str,
        tenant_id: str,
        item_code: Optional[str] = None,
        scoring_rounds: int = 1,
    ) -> Dict[str, Any]:
        """
        针对指定评估维度或单一评分项应用用户自定义微调指令重新打分，并实时无缝落库更新总分。

        :param db: 数据库 Session
        :param result_id: 打分结果记录 ID (UUID)
        :param category: 大类维度名称（如 '价格分'）
        :param user_instruction: 用户输入微调指令提示词
        :param tenant_id: 租户 ID
        :param item_code: 可选的目标评分项编号或标题，若指定则仅精细重算该单一项
        :param scoring_rounds: 重算轮数（默认 1 轮）
        :return: 包含最新逐项明细与总分的报告数据字典
        """
        from app.db.crud.bid_score import bid_score_crud
        from app.db.models.bid_score import BidScoreResult, BidScoreItem
        from app.db.models.metadata import EvaluationMetadata
        from app.agents.tools.bid_scorer_tools import (
            retrieve_bid_content_for_category,
            llm_score_batch,
            compute_consensus,
            extract_missing_keywords_from_round,
            active_refine_context_with_keywords,
        )

        score_result = db.query(BidScoreResult).filter(
            BidScoreResult.id == result_id,
            BidScoreResult.tenant_id == tenant_id,
        ).first()

        if not score_result:
            raise ValueError(f"打分结果未找到 (result_id={result_id})")

        document_id = score_result.document_id
        source_doc_id = score_result.source_doc_id

        # 查找关联招标文档的 score_tree
        eval_meta = db.query(EvaluationMetadata).filter(
            EvaluationMetadata.document_id == source_doc_id
        ).first()

        if not eval_meta or not eval_meta.score_tree:
            raise ValueError(f"无法读取招标文件评分大纲 (source_doc_id={source_doc_id})")

        # 提取目标 category 下的评分项
        items_in_category = [
            item for item in eval_meta.score_tree
            if item.get("category") == category
        ]

        if not items_in_category:
            raise ValueError(f"在大纲中未查找到维度 [{category}] 的评分细则")

        # 如果指定了具体的 item_code 或 title，精细过滤为仅重算该单一评分项
        items_to_score = items_in_category
        if item_code and item_code.strip():
            target_kw = item_code.strip()
            filtered = [
                i for i in items_in_category
                if str(i.get("item_code") or "").strip() == target_kw
                or str(i.get("title") or "").strip() == target_kw
            ]
            if filtered:
                items_to_score = filtered

        logger.info(
            f"🔄 [Rescore] 启动精细微调重算: result_id={result_id}, "
            f"category={category}, 目标评分项数={len(items_to_score)}, "
            f"指令='{user_instruction[:40]}'"
        )

        # 1. 执行多级 RAG 检索
        bid_content = retrieve_bid_content_for_category(document_id, items_to_score)

        # 2. Agentic Active RAG：第 1 轮初审 + 缺项反思二次提问追问
        round_results = []
        r1_result = llm_score_batch(
            items=items_to_score,
            bid_content=bid_content,
            round_idx=0,
            category=category,
            user_instruction=user_instruction,
        )
        round_results.append(r1_result)

        # 检查第 1 轮扣分项中是否有“缺少/未包含某些细节”
        missing_kws = extract_missing_keywords_from_round(r1_result)
        if missing_kws and document_id:
            logger.info(f"💡 [Rescore Active RAG] 微调第 1 轮初审发现缺项反思关键词: {missing_kws}，启动 Agentic 动态补全...")
            bid_content = active_refine_context_with_keywords(
                document_id=document_id,
                bid_content=bid_content,
                missing_keywords=missing_kws,
            )

        # 第 2~N 轮：基于（可能已扩充）的最新上下文执行终审评估
        for r_idx in range(1, scoring_rounds):
            batch_result = llm_score_batch(
                items=items_to_score,
                bid_content=bid_content,
                round_idx=r_idx,
                category=category,
                user_instruction=user_instruction,
            )
            round_results.append(batch_result)

        # 3. 计算共识/选优中位数
        consensus_results = compute_consensus(items_to_score, round_results, category)

        # 4. 事务级更新数据库中的 BidScoreItem
        for consensus in consensus_results:
            code = consensus["item_code"]
            db_item = db.query(BidScoreItem).filter(
                BidScoreItem.score_result_id == result_id,
                BidScoreItem.category == category,
                (BidScoreItem.item_code == code) | (BidScoreItem.title == consensus.get("title")),
            ).first()

            if db_item:
                db_item.ai_score = consensus["ai_score"]
                db_item.confidence = consensus["confidence"]
                db_item.score_variance = consensus["score_variance"]
                db_item.all_round_scores = consensus["all_round_scores"]
                db_item.scoring_basis = consensus["scoring_basis"]
                db_item.deduction_reason = consensus["deduction_reason"]
                db_item.suggestion = consensus["suggestion"]

        db.flush()

        # 5. 重新汇算全局总分、大类得分、校验告警与 Top 改进建议
        all_items = db.query(BidScoreItem).filter(BidScoreItem.score_result_id == result_id).all()
        new_total_score = round(sum(i.ai_score for i in all_items), 2)
        max_possible = score_result.max_possible or 100.0
        score_rate = round(new_total_score / max_possible, 4) if max_possible > 0 else 0.0

        cat_scores = dict(score_result.category_scores or {})
        cat_items = [i for i in all_items if i.category == category]
        cat_sum = round(sum(i.ai_score for i in cat_items), 2)
        cat_max = round(sum(i.max_score for i in cat_items), 2)

        cat_scores[category] = {
            "score": cat_sum,
            "max_total": cat_max,
            "count": len(cat_items),
        }

        # 重新生成 validation_warnings 告警
        new_warnings = []
        for c_name, c_info in cat_scores.items():
            if c_info.get("score", 0) == 0 and c_info.get("max_total", 0) > 0:
                new_warnings.append(
                    f"⚠️ [{c_name}] 所有评分项得 0 分，请检查投标文件是否缺失该部分内容"
                )

        # 重新计算 top_improvements (TOP 3 改进项)
        improvements = []
        for i in all_items:
            gap = round((i.max_score or 0) - (i.ai_score or 0), 2)
            if gap > 0:
                p_level = "P0" if gap >= 10 else ("P1" if gap >= 5 else "P2")
                improvements.append({
                    "priority": p_level,
                    "category": i.category,
                    "title": i.title,
                    "current_score": i.ai_score,
                    "potential_gain": gap,
                    "action": i.suggestion or i.deduction_reason or f"补充【{i.title}】在投标文稿中的具体内容与证明材料",
                })
        improvements.sort(key=lambda x: x["potential_gain"], reverse=True)
        top_improvements = improvements[:3]

        # 重新合成自然流畅的总体评价报告 (Overall Evaluation Report)
        summary_text = self._generate_rescore_expert_summary(
            category=category,
            user_instruction=user_instruction,
            new_total_score=new_total_score,
            max_possible=max_possible,
            score_rate=score_rate,
            cat_scores=cat_scores,
            top_improvements=top_improvements,
            tenant_id=tenant_id,
        )

        score_result.total_score = new_total_score
        score_result.score_rate = score_rate
        score_result.category_scores = cat_scores
        score_result.validation_warnings = new_warnings
        score_result.top_improvements = top_improvements
        score_result.summary = summary_text

        db.commit()
        db.refresh(score_result)

        logger.success(
            f"✅ [Rescore] 微调重算成功: category={category}, "
            f"大类得分={cat_sum}/{cat_max}, 全局总分={new_total_score}/{max_possible}"
        )

        return db.query(BidScoreResult).filter(BidScoreResult.id == result_id).first()

    # ============================================================
    # 4. 人工切片与章节标注编排 (Human Annotation Workflow)
    # ============================================================

    def get_document_chunks_for_annotation(
        self,
        db: Session,
        document_id: str,
        user_id: str,
        tenant_id: str,
    ) -> List[DocChunk]:
        """
        获取指定文档的全量切片列表，用于前端可视化渲染与人工章节标注。
        """
        doc = db.query(Document).filter(
            Document.id == document_id,
            Document.user_id == user_id,
            Document.tenant_id == tenant_id,
        ).first()

        if not doc:
            raise ValueError(f"文档未找到或无访问权限 (document_id={document_id})")

        return db.query(DocChunk).filter(
            DocChunk.document_id == document_id
        ).order_by(DocChunk.chunk_index).all()

    def save_human_annotated_chunks(
        self,
        db: Session,
        document_id: str,
        chunk_updates: List[Any],
        user_id: str,
        tenant_id: str,
    ) -> Dict[str, Any]:
        """
        保存人工修饰或重组后的切片标注数据，自动批量重新计算 Embeddings 向量并覆盖更新。
        """
        doc = db.query(Document).filter(
            Document.id == document_id,
            Document.user_id == user_id,
            Document.tenant_id == tenant_id,
        ).first()

        if not doc:
            raise ValueError(f"文档未找到或无访问权限 (document_id={document_id})")

        if not chunk_updates:
            raise ValueError("提交的切片更新列表不能为空")

        logger.info(f"✏️ 接收到文档 ({document_id}) 的人工标注更新请求，共 {len(chunk_updates)} 块切片")

        # 1. 尝试加载底层原始 PDF 文件，以实现 100% 物理页码精准物理提取
        pdf_doc = None
        if doc and doc.file_path and os.path.exists(doc.file_path) and doc.file_path.lower().endswith(".pdf"):
            try:
                import fitz
                pdf_doc = fitz.open(doc.file_path)
                logger.info(f"📄 成功加载原始 PDF (共 {len(pdf_doc)} 页)，启用 PyMuPDF 物理页码精准抓取引擎")
            except Exception as pdf_err:
                logger.warning(f"无法打开原始 PDF 文件 ({doc.file_path}): {pdf_err}")

        # 预先拉取数据库现存的原始切片正文作为二级保底
        existing_chunks = db.query(DocChunk).filter(DocChunk.document_id == document_id).all()
        page_to_real_contents = {}
        for ec in existing_chunks:
            p = ec.page_num or 1
            if p not in page_to_real_contents:
                page_to_real_contents[p] = []
            if ec.content and not ec.content.startswith("📄 原文档第") and not ec.content.startswith("原文档第"):
                page_to_real_contents[p].append(ec.content)

        # 2. 检查并修正提交的切片文本 (优先从 PyMuPDF 物理页提取 100% 精准正文)
        final_contents = []
        import re
        for item in chunk_updates:
            c_text = item.content or ""
            if not c_text.strip() or c_text.startswith("📄 原文档第") or c_text.startswith("原文档第"):
                # 从占位符或 item.page_num 中提取起始页码与结束页码
                s_page = item.page_num or 1
                e_page = s_page
                match = re.search(r"第\s*(\d+)\s*页至第\s*(\d+)\s*页", c_text)
                if match:
                    s_page = int(match.group(1))
                    e_page = int(match.group(2))
                
                # 优先从底层 PDF 物理页精准提取文本
                if pdf_doc:
                    extracted_texts = []
                    for p in range(s_page, e_page + 1):
                        if 1 <= p <= len(pdf_doc):
                            page_t = pdf_doc[p - 1].get_text().strip()
                            if page_t:
                                extracted_texts.append(f"--- [原文档第 {p} 页] ---\n{page_t}")
                    if extracted_texts:
                        c_text = "\n\n".join(extracted_texts)

                # 若无 PDF 句柄，降级使用数据库存量真实文本
                if not c_text or c_text.startswith("📄 原文档第") or c_text.startswith("原文档第"):
                    matched_texts = []
                    for p in range(s_page, e_page + 1):
                        matched_texts.extend(page_to_real_contents.get(p, []))
                    if matched_texts:
                        c_text = "\n\n".join(matched_texts)
                    else:
                        c_text = item.content or f"原文档第 {s_page}~{e_page} 页正文"

            item.content = c_text
            final_contents.append(c_text)

        if pdf_doc:
            pdf_doc.close()

        # 3. 为修正后的真实标书原文重新计算 1024 维 Vector Embeddings
        try:
            embeddings = llm_service.generate_embeddings(final_contents)
        except Exception as e:
            logger.error(f"❌ 为人工标注切片生成向量失败: {str(e)}")
            raise RuntimeError(f"生成切片向量失败: {str(e)}")

        # 4. 清理旧切片
        db.query(DocChunk).filter(DocChunk.document_id == document_id).delete()

        # 5. 重新插入更新后的切片 (保存 MinerU 真实原文)
        new_chunk_objs = []
        for idx, item in enumerate(chunk_updates):
            chunk_obj = DocChunk(
                tenant_id=tenant_id,
                user_id=user_id,
                document_id=document_id,
                chunk_index=idx,
                section_title=item.section_title or "无章节/正文",
                content=item.content,
                page_num=item.page_num or 1,
                trace_info={
                    "parent_chapter": item.parent_chapter or item.section_title or "无章节/正文",
                    "human_annotated": True,
                },
                embedding=embeddings[idx] if idx < len(embeddings) else None,
            )
            new_chunk_objs.append(chunk_obj)

        db.add_all(new_chunk_objs)

        # 4. 更新文档的元数据标记
        metadata = dict(doc.parsed_metadata or {})
        metadata["human_annotated"] = True
        metadata["chunk_count"] = len(new_chunk_objs)
        doc.parsed_metadata = metadata

        db.commit()
        db.refresh(doc)

        logger.success(f"✅ 文档 ({document_id}) 人工切片标注保存成功！写入 {len(new_chunk_objs)} 块更新切片")
        return {
            "document_id": document_id,
            "chunk_count": len(new_chunk_objs),
            "human_annotated": True,
            "message": f"成功保存 {len(new_chunk_objs)} 块切片并更新向量"
        }



    # ============================================================
    # 内部辅助方法
    # ============================================================

    @staticmethod
    def _compute_file_hash(file_path: str) -> str:
        """
        计算文件的 MD5 哈希值。

        :param file_path: 文件路径
        :return: 16 进制哈希字符串
        """
        with open(file_path, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()

    @staticmethod
    def _find_existing_parsed_doc(
        db: Session,
        project_id: str,
        filename: str,
        file_hash: str,
    ) -> Optional[Document]:
        """
        查找是否已有同名同内容且已完成解析的文档记录。

        :param db: 数据库会话
        :param project_id: 项目 ID
        :param filename: 文件名
        :param file_hash: 文件哈希
        :return: 匹配的 Document 或 None
        """
        docs = db.query(Document).filter(
            Document.project_id == project_id,
            Document.filename == filename,
            Document.parse_status == "completed",
        ).all()

        for doc in docs:
            meta = doc.parsed_metadata or {}
            if meta.get("file_hash") == file_hash and meta.get("doc_type") == "bid":
                # 防御性核检：判断切片表（doc_chunks）里实际是否存在该档对应的完整碎片
                chunk_count = db.query(DocChunk).filter(DocChunk.document_id == doc.id).count()
                if chunk_count > 0:
                    return doc
                else:
                    logger.warning(
                        f"⚠️ 缓存失效防御：文档（doc_id={doc.id}）状态为 'completed'，但其实际数据已被手工移除。作废遗留凭证并重启全域重建解析！"
                    )
                    db.delete(doc)
                    db.flush()
        return None


# 全局单例
bid_scorer_service = BidScorerService()
