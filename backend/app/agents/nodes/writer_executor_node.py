"""
章节任务并发执行器 (WriterExecutorNode)

功能：
1. 接收从 Planner 拆解出的 ChapterTask 章节任务列表；
2. 调度 Writer Tools 检索资质中心数据库 (CompanyQualification)、成本底价数据与章节特定条款；
3. 按任务类型 (template_fill / schema_table / generative_essay / compliance_matrix) 并发调度 Worker 执行精细化填空与表格装配；
4. 将填空后的文本段落、生成的结构化数据表填入对应的任务结果集中。
"""

import asyncio
from typing import Dict, Any, List, Optional
from loguru import logger
from app.agents.nodes.writer_planner_node import ChapterTask
from app.agents.nodes.writer_agent import num_to_rmb_chinese
from app.services.llm_service import llm_service
from app.agents.tools.writer_tools import (
    get_company_qualifications_tool,
    get_cost_estimation_data_tool,
    retrieve_chapter_clause_requirements
)


async def execute_single_chapter_task(
    task: ChapterTask, 
    metadata: Dict[str, Any], 
    analysis: Dict[str, Any],
    document_id: Optional[str] = None,
    tenant_id: Optional[str] = "default-tenant"
) -> Dict[str, Any]:
    """
    单个章节任务的执行逻辑：结合章节具体要求、资质中心 DB 与成本底价，直接进行模版填空或数据装配。
    """
    hint = task.mapping_hint.lower()
    task_type = task.task_type

    logger.info(f"⚡ 开始执行章节任务 [{task.chapter_title}] -> 类型: {task_type}, 映射: {hint}")
    try:
        from app.worker.tasks import emit_agent_log
        emit_agent_log(
            log_type="info",
            content=f"⚡ [章节 Agent 填空] 正在处理章节：{task.chapter_title} (类型: {task_type})",
            extra={"type": "chapter_execution", "task_id": task.task_id, "chapter_title": task.chapter_title}
        )
    except Exception:
        pass

    result_payload: Dict[str, Any] = {
        "task_id": task.task_id,
        "chapter_title": task.chapter_title,
        "chapter_number": task.chapter_number,
        "mapping_hint": hint,
        "task_type": task_type,
        "filled_content": "",
        "table_rows": [],
    }

    # 0. 检索招标文件中针对该章节的特定填写要求与限制条款
    chapter_clause_req = ""
    if document_id:
        chapter_clause_req = retrieve_chapter_clause_requirements(document_id, task.chapter_title)

    # 1. 范本长段落/方案类 (按用户要求：暂不做纯大段 AI 撰写，保留招标格式要求提示框架)
    if task_type == "generative_essay" or hint in ["technical", "service", "schedule", "safety"]:
        hint_text = task.content_hint or task.template_markdown or chapter_clause_req or ""
        if hint_text:
            result_payload["filled_content"] = f"【招标格式要求/条款提示】:\n{hint_text}\n\n[此处按招标文件要求手动补充【{task.chapter_title}】的具体方案与相关证明材料]"
        else:
            result_payload["filled_content"] = f"[此处按招标文件要求手动补充【{task.chapter_title}】的具体方案与相关说明材料]"

    # 2. 偏离与响应表类 (compliance_matrix)
    elif task_type == "compliance_matrix" or hint in ["deviation", "risk"]:
        risks = analysis.get("risks_analysis", [])
        rows = []
        if risks:
            for i, r in enumerate(risks):
                rows.append({
                    "seq": str(i + 1),
                    "type": r.get("risk_type", "条款响应"),
                    "desc": r.get("description", "按招标文件要求响应"),
                    "status": "完全响应",
                    "reason": "无偏离"
                })
        else:
            rows.append({
                "seq": "1",
                "type": "商务/技术条款",
                "desc": "全部条款响应",
                "status": "完全响应",
                "reason": "无偏离，符合招标文件规定"
            })
        result_payload["table_rows"] = rows

    # 3. 原生表格装配类 (schema_table)
    elif task_type == "schema_table" or hint in ["pricing", "cost", "qualification", "personnel", "performance"]:
        cost_data = get_cost_estimation_data_tool(analysis)
        cost_items = cost_data.get("cost_items", [])
        total_cost = cost_data.get("total_cost", 0.0)
        total_cost_rmb = cost_data.get("total_cost_rmb", "零元整")

        if hint in ["pricing", "cost"] and cost_items:
            result_payload["total_cost"] = total_cost
            result_payload["total_cost_rmb"] = total_cost_rmb
            result_payload["table_rows"] = cost_items
        elif hint in ["qualification"]:
            # 自动查询资质中心 DB 中的已解析证书
            quals = get_company_qualifications_tool(tenant_id)
            qual_rows = []
            if quals:
                for i, q in enumerate(quals):
                    qual_rows.append({
                        "seq": str(i + 1),
                        "name": q.get("name", ""),
                        "level": q.get("level", ""),
                        "expiry": q.get("expiry_date", ""),
                        "company": q.get("company_name", ""),
                        "file_url": q.get("file_url", "")
                    })
            result_payload["table_rows"] = qual_rows
            result_payload["filled_content"] = f"已自动匹配资质中心 DB 中 {len(quals)} 项公司有效证书及附件文件。"
        else:
            result_payload["filled_content"] = task.content_hint or "按招标文件格式如实填报"

    # 4. 表单与划线填空类 (template_fill)
    else:
        timeline = metadata.get("timeline", {})
        project_name = timeline.get("project_name") or ""
        project_id = timeline.get("project_id_code") or ""

        cost_data = get_cost_estimation_data_tool(analysis)
        total_cost = cost_data.get("total_cost", 0.0)
        total_cost_rmb = cost_data.get("total_cost_rmb", "零元整")

        contacts = timeline.get("contacts") or []
        tenderer = ""
        for c in contacts:
            if isinstance(c, dict) and ("招标" in c.get("role_type", "") or "甲方" in c.get("role_type", "")):
                tenderer = c.get("unit_name", "")
                if tenderer:
                    break

        template_text = task.template_markdown or task.content_hint or ""

        if template_text and len(template_text.strip()) > 20:
            # 使用 LLM 对原模版进行精准下划线/占位符置换
            prompt = f"""
你一位招投标文书排版与精确填空专家。
请阅读以下招标文件中【{task.chapter_title}】章节的模板与填写要求，
将其中的划线 `____`、括号或占位符精准替换为提供的项目实际商务与成本数据。

【章节具体填写要求/提示】:
{chapter_clause_req}

【示范文段 / 模版】:
{template_text}

【已知项目实际数据】:
- 项目名称: {project_name or '未指定'}
- 招标编号: {project_id or '未指定'}
- 招标人/买方单位: {tenderer or '招标人'}
- 投标报价总额: ¥{total_cost:,.2f} 元
- 投标报价大写: {total_cost_rmb}

【生成约束】:
1. 必须严格保留示范文段的书信/致辞/声明排版格式与段落结构；
2. 将文段中的划线 `____` 、下划线及占位符精准填充为对应的真实数据；
3. 彻底清除 '[此处手动补充]' 类占位符；
4. 直接输出填空置换完成后的完整 Markdown 文本。
"""
            try:
                filled_text = llm_service.generate_text(prompt=prompt, temperature=0.1)
                result_payload["filled_content"] = filled_text
            except Exception as e:
                logger.warning(f"LLM 填空失败，降级使用拼接规则: {e}")
                result_payload["filled_content"] = f"项目名称：{project_name}\n招标编号：{project_id}\n投标总价：人民币 {total_cost_rmb} (¥{total_cost:,.2f})"
        else:
            result_payload["filled_content"] = f"项目名称：{project_name}\n招标编号：{project_id}\n投标总价：人民币 {total_cost_rmb} (¥{total_cost:,.2f})"

        result_payload["project_name"] = project_name
        result_payload["project_id"] = project_id

    return result_payload


async def execute_all_chapter_tasks(
    tasks: List[ChapterTask], 
    metadata: Dict[str, Any], 
    analysis: Dict[str, Any],
    document_id: Optional[str] = None,
    tenant_id: Optional[str] = "default-tenant"
) -> Dict[str, Any]:
    """
    并发调度所有章节任务的精细化填空与数据装配执行器
    """
    logger.info(f"🚀 开始并发执行 {len(tasks)} 个章节模板填空任务...")
    results_list = await asyncio.gather(*[
        execute_single_chapter_task(
            task=task, 
            metadata=metadata, 
            analysis=analysis,
            document_id=document_id,
            tenant_id=tenant_id
        ) for task in tasks
    ])

    results_map = {res["task_id"]: res for res in results_list}
    logger.info(f"✅ 成功完成 {len(results_map)} 个章节模板填空任务")
    return results_map

