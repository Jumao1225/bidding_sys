# 标书打分 Agent (BidScorerAgent) — 架构设计方案

> 创建日期：2026-07-28  
> 状态：设计完成，待实施  
> 作者：AI Agent + 用户协同

---

## 1. 背景与核心目标

在现有系统中，`EvaluationService` 已从招标文件中提取出完整的评分维度树 (`score_tree`) 并落库至 `evaluation_metadata` 表。

**BidScorerAgent 的使命**：读取这些评分维度，基于 RAG 检索我方标书内容，模拟评标专家逐项打分，给出**最终得分 + 逐项扣分分析 + 优化建议**。

### 1.1 核心需求确认

| 需求项 | 确认结果 |
|--------|----------|
| 打分对象 | 我方编制的标书（自评自检，非竞品） |
| 评分来源 | 唯一来源：`evaluation_metadata.score_tree` |
| 打分目的 | 给出最终得分 + 失分项分析 + 优化建议 |
| 一致性要求 | 三轮打分取中位数，抗 LLM 抖动 |

---

## 2. 架构选型论证 — 为什么是 Map-Reduce？

### 2.1 项目中已有的 4 种 Agent 架构模式

| 架构模式 | 代表实现 | 核心特征 | 适用场景 |
|----------|----------|----------|----------|
| **ReAct Agent** | `master_agent_node` (supervisor.py) | 单 Agent + Tool Calling 循环，自主决策调用工具 | 需要自主探索、结果不确定的提取任务 |
| **Supervisor-Worker** | `BidFillerAgent.agent_fill_node` (bid_filler_agent.py) | Supervisor ReAct Agent 持有 4 个决策工具，内部 dispatch Worker ReAct Agents（ThreadPoolExecutor 并发） | 章节识别 → 分类 → 动态派发，任务种类多样 |
| **Hub-and-Spoke** | `build_bidding_graph` (graph/builder.py) | Supervisor 节点 + conditional_edges 动态路由 5 个 Worker 节点，形成星型拓扑 | 多阶段依赖编排，需要动态调度顺序 |
| **Linear Pipeline** | `build_bid_filler_graph` (bid_filler_agent.py) | 4 个 Node 线性串联 (scan → fill → review → write)，固定顺序 | 流程确定、每步依赖上一步输出 |

### 2.2 BidScorerAgent 的任务特征分析

| 特征 | 分析 | 架构推论 |
|------|------|----------|
| 输入确定性 | `score_tree` 来自 DB，评分项完全确定 | ❌ 不需要 ReAct 自主探索 |
| 项间独立性 | 同一 `category` 下的评分项共享上下文，不同 category 完全独立 | ✅ 适合按 category 并行 |
| 输出结构化 | 每项输出固定 schema：`{ai_score, confidence, basis, ...}` | ❌ 不需要 Supervisor 动态决策 |
| 一致性要求 | 需要多轮打分取中位数 | ✅ 需要控制循环，不适合 ReAct |
| 性能要求 | 评分项可能有 20~50 项，需要并行 | ✅ 适合 Map-Reduce Fan-out |

### 2.3 最终选型

**LangGraph Map-Reduce Pipeline + 三轮共识投票**

使用 LangGraph `Send()` API 实现 category 级别的确定性并行 fan-out，每个 category 独立完成 RAG 检索 + LLM 结构化打分，最后 fan-in 聚合。**不使用 ReAct Agent**——因为打分任务是确定性的，不需要 Agent 自主探索。

---

## 3. 整体架构图

```
                    ┌──────────────────────────────────────────────────────┐
                    │         LangGraph StateGraph — Map-Reduce           │
                    │                                                      │
                    │  ┌─────────────┐                                     │
                    │  │  load_node  │  加载评分维度 + 验证标书             │
                    │  └──────┬──────┘                                     │
                    │         │  Send() × N categories                     │
                    │    ┌────┼────┬────────┐                              │
                    │    ▼    ▼    ▼        ▼                              │
                    │  ┌───┐┌───┐┌───┐  ┌─────┐                           │
                    │  │技 ││商 ││价 │  │ ... │  score_category_node      │
                    │  │术 ││务 ││格 │  │     │  (RAG + LLM × 3轮共识)    │
                    │  │分 ││分 ││分 │  │     │                           │
                    │  └─┬─┘└─┬─┘└─┬─┘  └──┬──┘                           │
                    │    └────┼────┴────────┘                              │
                    │         ▼  Fan-in (Annotated[list, operator.add])    │
                    │  ┌──────────────┐                                    │
                    │  │aggregate_node│  聚合 + 数学校验                    │
                    │  └──────┬───────┘                                    │
                    │         ▼                                            │
                    │  ┌──────────────┐                                    │
                    │  │ report_node  │  LLM 总评 + 持久化落库             │
                    │  └──────────────┘                                    │
                    └──────────────────────────────────────────────────────┘

数据依赖：
- load_node  ← 读取 evaluation_metadata (score_tree / weights)
- score_*    ← RAG 检索 doc_chunks (标书向量内容)
- report     → 写入 bid_score_results + bid_score_items
```

### 与 BidFillerAgent 架构对比

```
BidFillerAgent (Linear Pipeline + 内嵌 Supervisor-Worker):
  scan → [Supervisor ReAct Agent → ThreadPoolExecutor(Workers)] → review → write
  
BidScorerAgent (Map-Reduce Pipeline + 三轮共识):
  load → [Send() × N categories → 并行 LLM×3轮打分] → aggregate → report
```

关键区别：
1. **BidFiller** 用 ReAct Agent 做 Supervisor 决策（因为章节分类不确定），Worker 也是 ReAct Agent（因为需要自主选择工具查库）
2. **BidScorer** 完全不用 ReAct Agent（评分项已确定、工具调用路径固定），用 `Send()` 做确定性并行（更高效、更可控）

---

## 4. 核心设计详解

### 4.1 State 定义

```python
from typing import TypedDict, List, Dict, Any, Optional, Annotated
import operator

class BidScorerState(TypedDict):
    """BidScorerAgent 的全局状态"""
    # --- 输入参数 ---
    document_id: str          # 被评分的标书文档 ID（我方标书的 doc_chunks 所属）
    source_doc_id: str        # 招标文件 ID（评分维度来源，关联 evaluation_metadata）
    user_id: str
    tenant_id: str

    # --- load_node 产出 ---
    score_tree: List[dict]           # 从 DB 加载的完整评分维度树
    weight_distribution: dict        # 权重分布 {"技术分": 40, "商务分": 30, ...}
    evaluation_method: str           # 评标方法名称
    total_possible: float            # 满分值
    categories: List[str]            # 去重后的一级分类列表

    # --- score_category_node 并发产出 ---
    # Annotated[list, operator.add] 实现 fan-in 自动合并
    scored_items: Annotated[list, operator.add]

    # --- aggregate_node 产出 ---
    total_score: float
    score_rate: float
    category_scores: Dict[str, dict]  # 按 category 聚合的得分
    validation_warnings: List[str]    # 数学校验告警

    # --- report_node 产出 ---
    summary: str                     # LLM 生成的总体评价
    top_improvements: List[dict]     # 优先级排序的改进建议
    result_id: str                   # 落库后的打分记录 ID

    # --- 状态控制 ---
    status: str
    error: str
```

> **设计要点**：`scored_items: Annotated[list, operator.add]` 是 LangGraph 的 **Reducer 机制** —— 当多个并行的 `score_category_node` 实例各自返回 `{"scored_items": [...]}` 时，LangGraph 自动将它们 `+` 合并到主 State 中。这正是现有 `BiddingState` 中 `dispatched_steps` 和 `completed_steps` 使用的同一模式。

### 4.2 Node ① — `load_node`（纯 DB 读取，零 LLM 调用）

**职责**：
1. 读 `evaluation_metadata` 表，提取 `score_tree` / `weight_distribution` / `total_score`
2. 验证 `score_tree` 非空（否则 Early Return 报错退出）
3. 验证被评分标书的 `doc_chunks` 存在（否则报错退出）
4. 按 `category` 分组，产出 `categories` 列表

### 4.3 Node ② — `score_category_node`（核心打分引擎 — RAG + LLM × 3 轮共识）

通过 LangGraph `Send()` API，**每个 category 并行启动一个独立实例**。

**工作流**：
1. **批量 RAG 检索**：用该 category 下所有评分项的关键词一次性检索标书内容
2. **LLM 结构化打分 × 3 轮**：同一份上下文打分 3 次，取中位数
3. **防幻觉五重护栏校验**

**Prompt 设计**（遵循 CO-STAR 框架 + 防幻觉黄金标准）：
- **Context**：资深评标专家角色，15 年政府采购评标经验
- **Objective**：逐项对比评分细则与投标文件内容
- **Style**：评分依据必须直接引用原文（用「」标注引用），禁止模糊表述
- **Tone**：严谨客观，宁可少给分，不可多给分
- **Audience**：评标委员会主任
- **最高指令（防幻觉铁律）**：
  - 找不到对应内容 → 强制 0 分
  - 仅部分提及 → 阶梯打分
  - 严禁利用互联网常识补充
  - `ai_score` 绝不可超过 `max_score`

**三轮共识计算**：
- 每项取 3 轮分数的**中位数**
- 置信度 = `1 - 标准差/max_score`（分数越一致，置信度越高）
- 使用 `best_round`（最高置信度轮次）的文字描述作为最终评语

### 4.4 Map-Reduce 路由 — `Send()` API 并行 Fan-out

```python
from langgraph.graph import StateGraph, END, Send

def route_to_category_scorers(state: BidScorerState) -> list:
    """load_node 完成后，对每个 category 发出 Send()，LangGraph 自动并行执行"""
    if state.get("status") == "failed":
        return [Send("report_node", state)]
    return [Send("score_category_node", {**state, "current_category": cat})
            for cat in state["categories"]]

def build_bid_scorer_graph():
    workflow = StateGraph(BidScorerState)
    workflow.add_node("load_node", load_node)
    workflow.add_node("score_category_node", score_category_node)
    workflow.add_node("aggregate_node", aggregate_node)
    workflow.add_node("report_node", report_node)
    workflow.set_entry_point("load_node")
    workflow.add_conditional_edges("load_node", route_to_category_scorers,
                                   ["score_category_node", "report_node"])
    workflow.add_edge("score_category_node", "aggregate_node")
    workflow.add_edge("aggregate_node", "report_node")
    workflow.add_edge("report_node", END)
    return workflow.compile()
```

### 4.5 Node ③ — `aggregate_node`（纯计算，零 LLM）

**职责**：
1. 按 `category` 分组汇总得分
2. 计算 `total_score` 和 `score_rate`
3. 数学校验：子项分数之和 vs `weight_distribution` 的一致性
4. 标记校验告警（如某 category 所有项得 0 分、得分超过满分等）

### 4.6 Node ④ — `report_node`（LLM 总评 + 持久化）

**职责**：
1. 计算优先级排序的改进建议（按 `potential_gain` 降序）
2. 调用 LLM 生成自然语言总体评价摘要
3. 将全部结果落盘到 `bid_score_results` + `bid_score_items` 表

---

## 5. 防幻觉五重护栏

| 层级 | 护栏机制 | 实现位置 |
|------|----------|----------|
| **L1 数据源锁定** | 评分标准 100% 来自 DB `score_tree`，不接受 LLM 自创评分项 | `load_node` |
| **L2 RAG 兜底** | 检索不到相关内容 → 强制 0 分 + 标注"未在标书中发现" | `score_category_node` |
| **L3 分值截断** | `ai_score` 强制 `min(ai_score, max_score)` + `max(ai_score, 0)` | `score_category_node` |
| **L4 三轮共识** | 同一评分项打 3 次取中位数，标准差过大时降低 confidence | `_compute_consensus` |
| **L5 数学校验** | 子项加和 vs 总分交叉验证，异常时触发告警 | `aggregate_node` |

---

## 6. 数据库层设计

### 新增表

#### `bid_score_results` — 一次打分会话结果

| 字段 | 类型 | 说明 |
|------|------|------|
| id | String(36) PK | 主键 |
| document_id | String(36) FK | 被评分的标书文档 ID |
| source_doc_id | String(36) FK | 评分维度来源的招标文件 ID |
| evaluation_method | String(255) | 评标方法 |
| total_score | Float | AI 总分 |
| max_possible | Float | 满分 |
| score_rate | Float | 得分率 |
| category_scores | JSON | 按大类聚合的分数 |
| summary | Text | 总体评价摘要 |
| top_improvements | JSON | 改进建议 |
| validation_warnings | JSON | 校验告警 |
| scoring_rounds | Integer | 共识轮数 (默认 3) |
| model_name | String(255) | LLM 模型名称 |
| tenant_id | String(36) | 租户 ID |
| created_at | DateTime | 创建时间 |

#### `bid_score_items` — 逐项打分明细

| 字段 | 类型 | 说明 |
|------|------|------|
| id | String(36) PK | 主键 |
| score_result_id | String(36) FK | 关联打分会话 |
| item_code | String(100) | 评分项编号 |
| category | String(100) | 一级分类 |
| sub_category | String(100) | 二级分类 |
| title | String(500) | 评分项名称 |
| max_score | Float | 该项满分 |
| ai_score | Float | AI 打分（中位数） |
| confidence | Float | 置信度 |
| score_variance | Float | 三轮分数标准差 |
| all_round_scores | JSON | 三轮原始分数 |
| scoring_basis | Text | 评分依据（引用原文） |
| deduction_reason | Text | 扣分原因 |
| suggestion | Text | 改进建议 |
| tenant_id | String(36) | 租户 ID |
| created_at | DateTime | 创建时间 |

---

## 7. 完整文件清单

| 层级 | 操作 | 文件路径 | 说明 |
|------|------|----------|------|
| **Model** | NEW | `backend/app/db/models/bid_score.py` | 2 张新表定义 |
| **Model** | MODIFY | `backend/app/db/models/__init__.py` | 注册新模型 |
| **Migration** | NEW | `backend/alembic/versions/xxx_add_bid_score.py` | 自动生成迁移 |
| **CRUD** | NEW | `backend/app/db/crud/bid_score.py` | 打分结果 CRUD |
| **Schema** | NEW | `backend/app/schemas/bid_scorer_schema.py` | 请求/响应 Schema |
| **Agent** | NEW | `backend/app/agents/bid_scorer_agent.py` | **核心**: 4 节点 Map-Reduce StateGraph |
| **Tools** | NEW | `backend/app/agents/tools/bid_scorer_tools.py` | RAG 检索 + LLM 批量打分封装 |
| **Service** | NEW | `backend/app/services/bid_scorer_service.py` | 业务编排入口 |
| **API** | NEW | `backend/app/api/endpoints/bid_scorer.py` | 4 个 API 端点 |
| **API** | MODIFY | `backend/app/main.py` | 注册路由 |

---

## 8. API 端点设计

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/bid-scorer/score` | 触发对指定标书的 AI 打分 |
| GET | `/bid-scorer/results/{document_id}` | 获取指定标书的所有历史打分结果 |
| GET | `/bid-scorer/results/{document_id}/latest` | 获取最新一次打分结果 |
| GET | `/bid-scorer/detail/{result_id}` | 获取某次打分的逐项明细 |

---

## 9. 验证计划

### 自动化测试

```bash
# 单元测试 — 共识计算 + 护栏逻辑
pytest tests/unit/test_bid_scorer_consensus.py -v

# 集成测试 — 完整 Map-Reduce 打分流程
pytest tests/integration/test_bid_scorer_flow.py -v

# API 接口测试
pytest tests/api/test_bid_scorer_api.py -v
```

### 手工验证

1. 确认 `evaluation_metadata.score_tree` 已有数据（通过前序流程生成）
2. 确认标书文档已完成解析（`doc_chunks` 存在且有向量）
3. 调用 `POST /bid-scorer/score` 触发打分
4. 验证返回报告：逐项分数 + 三轮原始分数 + 总分 + 改进建议
5. 验证数据库 `bid_score_results` 和 `bid_score_items` 已落库
6. 重复调用验证：得分波动应在 ±3% 以内（三轮共识生效）
