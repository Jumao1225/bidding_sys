"""
投标文件格式大章拆解与动态任务规划器 (WriterPlannerNode)

功能：
1. 提取招标文件中的【投标文件格式】章节大纲及原文档模版；
2. 按照「一章节 = 一任务 = 一原模版」的原则，将格式大章拆解为多个 ChapterTask 任务；
3. 为每个任务绑定该章节原模版的提示说明、范例格式以及对应的数据库元数据依赖。
"""

import os
from typing import List, Optional, Literal
from loguru import logger
from pydantic import BaseModel, Field
from app.agents.state import BiddingState
from app.services.llm_service import llm_service


class ChapterTask(BaseModel):
    """
    单章节动态填空/撰写任务定义 (一章节一任务一原模版)
    """
    task_id: Optional[str] = Field(None, description="章节任务唯一标识 (如 'task_01_bid_letter')")
    chapter_number: str = Field(..., description="章节编号 (如 '一'、'（二）'、'1.1')")
    chapter_title: str = Field(..., description="章节标题 (如 '一、投标函')")
    mapping_hint: str = Field(
        ..., 
        description="数据与策略映射标签: bid_letter / authorization / qualification / pricing / technical / deviation / service / personnel / performance / financial / schedule / safety / _unknown"
    )
    task_type: Literal["template_fill", "schema_table", "generative_essay", "compliance_matrix"] = Field(
        ...,
        description="填空模式: template_fill(原文表单/下划线填空), schema_table(原生表格数据装配), generative_essay(技术/施工方案AI撰写), compliance_matrix(偏离响应对照)"
    )
    content_hint: Optional[str] = Field(None, description="招标方对该章节格式的填写提示/要求说明")
    template_markdown: Optional[str] = Field(None, description="招标方在该章节给出的原汁原味的示范文段或 Markdown 样例表格")
    required_context_keys: List[str] = Field(
        default_factory=list,
        description="该任务依赖的数据元数据键，如 ['timeline', 'financial', 'engineering', 'qualification', 'cost_analysis']"
    )


class ChapterPlan(BaseModel):
    """
    标书动态任务计划清单
    """
    source_chapter: str = Field("投标文件格式", description="来源章节名称")
    tasks: List[ChapterTask] = Field(default_factory=list, description="拆解出的所有章节任务列表")


def plan_chapter_tasks_from_markdown(format_chapter_text: str) -> List[ChapterTask]:
    """
    使用大模型将投标文件格式大章拆解为一章节一任务的动态任务列表。
    """
    if not format_chapter_text or len(format_chapter_text.strip()) < 50:
        logger.warning("格式章节文本过短，降级使用默认目录任务结构")
        return get_default_chapter_tasks()

    prompt = f"""
你是一位招投标编制总控专家。请认真分析以下招标文件中的【投标文件格式】大章原文，
将其拆解为多个独立的【章节任务清单】(一章节 = 一任务 = 一原模版)。

【投标文件格式原文】:
{format_chapter_text}

【拆解规则】:
1. 请逐一识别招标文件中要求投标方提交的所有大章、附件或表格小节（如“一、投标函”、“二、法定代表人授权书”、“三、开标一览表”、“四、技术方案”等）。
2. 为每一个章节生成一个 ChapterTask 对象。
3. mapping_hint 必须选自以下之一：
   - bid_letter: 投标函/投标声明
   - authorization: 法定代表人授权书/委托书
   - qualification: 资格审查资料/资质证明
   - pricing / cost: 商务报价/开标一览表/分项报价表
   - technical: 技术方案/施工组织设计/设备选型
   - deviation / risk: 偏离表/商务技术偏离
   - service / warranty: 售后服务承诺/质保承诺
   - personnel: 拟派团队人员表/项目经理
   - performance: 业绩清单/同类项目业绩
   - financial: 财务报表/资信证明
   - schedule: 工期计划/进度安排
   - safety: 安全生产方案/文明施工
   - _unknown: 其他自定义章节
4. task_type 判断规范：
   - 如果是投标函、授权书等带划线或固定表单的：置为 "template_fill"
   - 如果是开标一览表、报价明细表、人员表等表格：置为 "schema_table"
   - 如果是技术方案、施工组织、售后服务等长段落撰写：置为 "generative_essay"
   - 如果是实质性条款/商务技术偏离表：置为 "compliance_matrix"
5. template_markdown：必须将原文中该章节原汁原味的示范段落（如“致：XXX...”、“买方的___号”）或 Markdown 样表完整提取保留！不要删减！

如果原文未检测到明确章节，请返回空 tasks 列表。
"""

    try:
        plan_obj: ChapterPlan = llm_service.generate_structured_output(
            prompt=prompt,
            schema_cls=ChapterPlan,
            temperature=0.0
        )
        if plan_obj and plan_obj.tasks:
            # 防御性补全缺失的 task_id
            for idx, t in enumerate(plan_obj.tasks):
                if not t.task_id:
                    t.task_id = f"task_{idx+1:02d}_{t.mapping_hint}"

            logger.info(f"成功将标书格式大章拆解为 {len(plan_obj.tasks)} 个章节任务")
            try:
                from app.worker.tasks import emit_agent_log
                emit_agent_log(
                    log_type="info",
                    content=f"📋 动态拆解标书格式大章成功，共生成 {len(plan_obj.tasks)} 个章节任务 (一章节一模版)",
                    extra={"type": "planner_tasks", "task_count": len(plan_obj.tasks)}
                )
            except Exception:
                pass
            return plan_obj.tasks

    except Exception as e:
        logger.error(f"拆解标书格式大章任务发生异常: {e}")


    return get_default_chapter_tasks()


def get_default_chapter_tasks() -> List[ChapterTask]:
    """
    降级兜底：当未提取到招标文件格式时，提供标准投标书默认章节任务列表
    """
    return [
        ChapterTask(
            task_id="task_01_bid_letter",
            chapter_number="一",
            chapter_title="一、投标函",
            mapping_hint="bid_letter",
            task_type="template_fill",
            required_context_keys=["timeline"]
        ),
        ChapterTask(
            task_id="task_02_auth",
            chapter_number="二",
            chapter_title="二、法定代表人授权书",
            mapping_hint="authorization",
            task_type="template_fill",
            required_context_keys=["timeline"]
        ),
        ChapterTask(
            task_id="task_03_qual",
            chapter_number="三",
            chapter_title="三、资格审查资料",
            mapping_hint="qualification",
            task_type="schema_table",
            required_context_keys=["qualification", "qualifications_analysis"]
        ),
        ChapterTask(
            task_id="task_04_cost",
            chapter_number="四",
            chapter_title="四、商务报价与开标一览表",
            mapping_hint="pricing",
            task_type="schema_table",
            required_context_keys=["financial", "cost_analysis"]
        ),
        ChapterTask(
            task_id="task_05_tech",
            chapter_number="五",
            chapter_title="五、技术方案",
            mapping_hint="technical",
            task_type="generative_essay",
            required_context_keys=["engineering"]
        ),
        ChapterTask(
            task_id="task_06_dev",
            chapter_number="六",
            chapter_title="六、商务及技术偏离表",
            mapping_hint="deviation",
            task_type="compliance_matrix",
            required_context_keys=["risks_analysis"]
        ),
        ChapterTask(
            task_id="task_07_personnel",
            chapter_number="七",
            chapter_title="七、拟投入项目人员表",
            mapping_hint="personnel",
            task_type="schema_table",
            required_context_keys=["qualification"]
        ),
        ChapterTask(
            task_id="task_08_perf",
            chapter_number="八",
            chapter_title="八、同类项目业绩清单",
            mapping_hint="performance",
            task_type="schema_table",
            required_context_keys=["qualification"]
        ),
        ChapterTask(
            task_id="task_09_service",
            chapter_number="九",
            chapter_title="九、售后服务承诺",
            mapping_hint="service",
            task_type="generative_essay",
            required_context_keys=["evaluation"]
        ),
    ]
