# Agent 架构改造完整方案（后端 + 前端）

> **创建日期**：2026-07-21  
> **状态**：待实施（用户已审阅，待执行批准）  
> **确认决策**：方案A（结构化输出调度）+ 最多重试 2 次

---

## 一、背景与问题

### 现有架构（Workflow）

```
[固定顺序，程序员决定]
parser_worker → master_agent → analyze_qualifications → identify_risks → cost_estimation → END
```

**弊端**：
- 所有节点顺序写死，无论标书内容如何，都必须按同一顺序全部执行
- `writer_agent.py` 文件存在但从未被接入图，是"空悬代码"
- Supervisor（大脑）的概念不存在，Agent 系统徒有其名

### 目标架构（Supervisor Agent）

```
[第一阶段 - 固定] parser_worker（解析是物理前提，无需动态调度）
       ↓
[第二阶段 - 动态] Supervisor Agent（LLM 大脑，structured_output 方案A决策）
       ↓ 动态路由（每个 Worker 完成后汇报，最多重试 2 次）
  ┌────┬────┬────┬────┬──────┐
master qual risk cost writer  → 各自汇报回 Supervisor
  └────┴────┴────┴────┴──────┘
       ↓（LLM 宣告 FINISH）
     结束
```

---

## 二、架构对比总结

| 维度 | 改造前（Workflow） | 改造后（Supervisor Agent） |
|------|---------------------|---------------------------|
| 调度方式 | 程序员写死 DAG | LLM 动态决策 |
| 节点顺序 | 固定不变 | 按需调度，可跳过 |
| 失败处理 | 直接终止 | 重试最多2次后跳过 |
| writer_agent | 空悬，未接入 | 首次真正接入 |
| 前端可视化 | 线性日志流 | 调度控制台 + Worker 状态矩阵 |
| 系统自主性 | 低（Workflow） | 高（Agentic System） |

---

## 三、后端改动详情

### 3.1 [MODIFY] `backend/app/agents/state.py`

扩展 `BiddingState`，新增 Supervisor 调度所需字段：

```python
from typing import TypedDict, List, Dict, Any

class BiddingState(TypedDict):
    # --- 基础信息（不变）---
    task_id: str
    document_id: str
    user_id: str
    tenant_id: str
    company_quals: str

    # --- Supervisor 调度所需（新增）---
    next: str                      # Supervisor 决定的下一步节点名
    completed_steps: List[str]     # 已完成步骤，防止重复调度
    worker_summaries: List[Dict]   # Worker 执行摘要，供 Supervisor 参考
    retry_counts: Dict[str, int]   # 各节点重试次数（上限 2 次）

    # --- 分析结果（不变）---
    qualifications_analysis: Dict[str, Any]
    risks_analysis: List[Dict[str, Any]]
    cost_analysis: Dict[str, Any]

    # --- 状态控制（不变）---
    status: str
    error: str
```

---

### 3.2 [NEW] `backend/app/agents/orchestrator.py`

Supervisor 节点核心实现：

```python
from typing import Literal
from pydantic import BaseModel
from loguru import logger

from app.agents.state import BiddingState
from app.services.llm_service import llm_service
from app.worker.tasks import emit_agent_log

# --- 常量 ---
MAX_RETRIES = 2  # 用户确认：最多重试 2 次

WORKER_DESCRIPTIONS = {
    "master_agent":    "提取5大核心元数据（资质/财务/时限/工况/评标），必须最先执行",
    "strategy_qual":   "资质三级评估（可做到/努力可做到/做不到），依赖 master_agent",
    "strategy_risk":   "风险条款扫描（商务/法务/财务风险），依赖 master_agent",
    "cost_estimation": "BOM提取 + 价格库语义匹配成本测算，依赖 master_agent",
    "writer_agent":    "生成投标书草稿（Word文档），依赖前三者",
}

class SupervisorDecision(BaseModel):
    next: Literal[
        "master_agent", "strategy_qual", "strategy_risk",
        "cost_estimation", "writer_agent", "FINISH"
    ]
    reasoning: str  # LLM 的决策理由，推送到前端终端展示


def build_supervisor_prompt(
    completed: list,
    retry_counts: dict,
    summaries: list,
    state: BiddingState
) -> str:
    """构造 Supervisor 决策 Prompt"""
    worker_status_lines = []
    for worker, desc in WORKER_DESCRIPTIONS.items():
        retries = retry_counts.get(worker, 0)
        if worker in completed:
            status = "✅ 已完成"
        elif retries >= MAX_RETRIES:
            status = f"⛔ 已超出最大重试次数({MAX_RETRIES}次)，跳过"
        else:
            status = f"⏳ 未执行" + (f"（已重试{retries}次）" if retries > 0 else "")
        worker_status_lines.append(f"  - {worker}：{desc} [{status}]")

    summary_text = "\n".join(
        [f"  - {s['worker']}: {s['summary']}" for s in summaries]
    ) or "  暂无"

    return f"""你是一位招标分析系统的总控 Supervisor Agent。
你的职责是根据当前各 Worker 的执行情况，决定下一步应该调用哪个 Worker，或者宣告任务完成。

【Worker 清单与当前状态】:
{chr(10).join(worker_status_lines)}

【各步骤执行摘要】:
{summary_text}

【调度规则】:
1. master_agent 必须最先执行（它为其他 Worker 提供元数据基础）
2. strategy_qual、strategy_risk、cost_estimation 均依赖 master_agent，可以并行但 LangGraph 顺序调度
3. writer_agent 依赖前三者均完成后才能执行
4. 同一 Worker 失败后最多重试 {MAX_RETRIES} 次，超限则跳过并继续
5. 所有可执行的 Worker 均已完成（或超限跳过）时，返回 FINISH
6. 宣告 FINISH 前，必须确保 strategy_qual/strategy_risk/cost_estimation 至少各执行成功或超限跳过一次

请根据以上状态，决定下一步行动，并用简洁的中文说明你的 reasoning。
"""


def supervisor_node(state: BiddingState) -> dict:
    """
    Supervisor 动态调度节点（核心大脑）。
    在每个 Worker 执行完成后被调用，决定下一步或宣告完成。
    """
    completed = state.get("completed_steps", [])
    retry_counts = state.get("retry_counts", {})
    summaries = state.get("worker_summaries", [])

    logger.info(f"Supervisor 正在决策，已完成步骤: {completed}，重试计数: {retry_counts}")
    emit_agent_log("info", f"🧠 Supervisor Agent 正在分析当前进度，决定下一步调度...")

    prompt = build_supervisor_prompt(completed, retry_counts, summaries, state)

    decision: SupervisorDecision = llm_service.generate_structured_output(
        prompt=prompt,
        schema_cls=SupervisorDecision,
        temperature=0.1
    )

    logger.info(f"Supervisor 决策 → [{decision.next}]，原因: {decision.reasoning}")
    emit_agent_log("supervisor_decision",
        f"🧠 Supervisor 决策 → [{decision.next}]\n原因：{decision.reasoning}"
    )

    # 同时以特殊格式推送，供前端 Worker 状态矩阵解析
    from app.worker.tasks import publish_progress
    from app.core.context import current_task_id
    task_id = current_task_id.get()
    if task_id:
        import json, redis
        from app.core.config import settings
        r = redis.from_url(settings.REDIS_URL)
        r.publish(f"channel:{task_id}", json.dumps({
            "status": "Supervisor 决策中...",
            "progress": 50,
            "agent_log": {
                "type": "supervisor_decision",
                "worker": decision.next if decision.next != "FINISH" else None,
                "reasoning": decision.reasoning,
                "completed_steps": completed,
                "retry_counts": retry_counts,
            }
        }, ensure_ascii=False))

    return {"next": decision.next}
```

---

### 3.3 [MODIFY] `backend/app/graph/builder.py`

从线性 DAG 改为 **Hub-and-Spoke（中心辐射）** 拓扑：

```python
from langgraph.graph import StateGraph, END
from app.agents.state import BiddingState
from app.agents.nodes.parser_worker import parser_worker_node
from app.agents.supervisor import master_agent_node
from app.agents.orchestrator import supervisor_node            # 新增
from app.agents.nodes.strategy_agent import analyze_qualifications_node, identify_risks_node
from app.agents.nodes.cost_agent import cost_node
from app.agents.nodes.writer_agent_node import writer_agent_node  # 新增


def route_after_parser(state: BiddingState) -> str:
    """解析器完成后，路由到 Supervisor（或失败终止）"""
    if state.get("status") == "parser_failed":
        return END
    return "supervisor"


def route_from_supervisor(state: BiddingState) -> str:
    """Supervisor 决策路由"""
    nxt = state.get("next", "FINISH")
    return END if nxt == "FINISH" else nxt


def build_bidding_graph():
    """构建 Supervisor Agent 编排图"""
    builder = StateGraph(BiddingState)

    # 注册所有节点
    builder.add_node("parser_worker",    parser_worker_node)
    builder.add_node("supervisor",       supervisor_node)       # 新增核心大脑
    builder.add_node("master_agent",     master_agent_node)
    builder.add_node("strategy_qual",    analyze_qualifications_node)
    builder.add_node("strategy_risk",    identify_risks_node)
    builder.add_node("cost_estimation",  cost_node)
    builder.add_node("writer_agent",     writer_agent_node)     # 首次接入

    # 入口：解析器固定第一步
    builder.set_entry_point("parser_worker")
    builder.add_conditional_edges(
        "parser_worker", route_after_parser, ["supervisor", END]
    )

    # Supervisor 动态路由（核心！）
    builder.add_conditional_edges("supervisor", route_from_supervisor, {
        "master_agent":    "master_agent",
        "strategy_qual":   "strategy_qual",
        "strategy_risk":   "strategy_risk",
        "cost_estimation": "cost_estimation",
        "writer_agent":    "writer_agent",
        END: END,
    })

    # 每个 Worker 执行完，回报给 Supervisor
    for worker in ["master_agent", "strategy_qual", "strategy_risk",
                   "cost_estimation", "writer_agent"]:
        builder.add_edge(worker, "supervisor")

    return builder.compile()


# 全局单例
bidding_graph = build_bidding_graph()
```

---

### 3.4 各 Worker 节点统一补充汇报字段

每个节点返回值需增加 `completed_steps` + `worker_summaries`，以供 Supervisor 感知进度。示例（以 `strategy_qual` 为例）：

```python
return {
    "qualifications_analysis": res,
    # Supervisor 依赖字段（新增）
    "completed_steps": state.get("completed_steps", []) + ["strategy_qual"],
    "worker_summaries": state.get("worker_summaries", []) + [{
        "worker": "strategy_qual",
        "status": "success",
        "summary": f"资质评估完成，共 {len(res.get('items', []))} 条要求，匹配得分 {res.get('match_score', 'N/A')}"
    }],
}
```

失败时的汇报：
```python
except Exception as e:
    return {
        "completed_steps": state.get("completed_steps", []) + ["strategy_qual"],
        "worker_summaries": state.get("worker_summaries", []) + [{
            "worker": "strategy_qual",
            "status": "failed",
            "summary": f"资质评估失败: {str(e)}"
        }],
        "retry_counts": {
            **state.get("retry_counts", {}),
            "strategy_qual": state.get("retry_counts", {}).get("strategy_qual", 0) + 1
        }
    }
```

---

### 3.5 [NEW] `backend/app/agents/nodes/writer_agent_node.py`

将现有 `writer_agent.py` 的 `WordGenerator` 包装为 LangGraph 节点：

```python
import os
from loguru import logger
from app.agents.state import BiddingState
from app.agents.nodes.writer_agent import WordGenerator
from app.core.audit_decorator import audit_node
from app.worker.tasks import emit_agent_log

@audit_node(name="WriterAgent-GenerateDraft")
def writer_agent_node(state: BiddingState) -> dict:
    """投标书草稿生成节点，依赖 qualifications/risks/cost 分析结果。"""
    document_id = state.get("document_id", "unknown")
    emit_agent_log("info", "✍️ WriterAgent 启动，开始生成投标书草稿...")

    analysis_results = {
        "qualifications": state.get("qualifications_analysis", {}),
        "risks":          state.get("risks_analysis", []),
        "cost":           state.get("cost_analysis", {}),
    }

    try:
        draft_bytes = WordGenerator.generate_bidding_draft(
            project_name=f"文档_{document_id[:8]}",
            analysis_results=analysis_results
        )
        # 落盘到临时目录
        output_dir = os.path.join("uploads", "drafts")
        os.makedirs(output_dir, exist_ok=True)
        draft_path = os.path.join(output_dir, f"draft_{document_id}.docx")
        with open(draft_path, "wb") as f:
            f.write(draft_bytes)

        emit_agent_log("success", f"✅ 投标书草稿已生成: {draft_path}")
        logger.info(f"WriterAgent 草稿落盘成功: {draft_path}")

        return {
            "completed_steps": state.get("completed_steps", []) + ["writer_agent"],
            "worker_summaries": state.get("worker_summaries", []) + [{
                "worker": "writer_agent",
                "status": "success",
                "summary": f"投标书草稿已生成，路径: {draft_path}"
            }],
        }
    except Exception as e:
        logger.exception("WriterAgent 执行失败")
        emit_agent_log("error", f"❌ 投标书草稿生成失败: {str(e)}")
        return {
            "completed_steps": state.get("completed_steps", []) + ["writer_agent"],
            "worker_summaries": state.get("worker_summaries", []) + [{
                "worker": "writer_agent",
                "status": "failed",
                "summary": str(e)
            }],
        }
```

---

## 四、新增 SSE 消息协议

后端需在推送中支持以下新消息类型，前端据此更新 Worker 状态矩阵：

| 消息类型 (`type`) | 触发时机 | 关键字段 |
|---|---|---|
| `supervisor_decision` | Supervisor 每次决策后 | `reasoning`, `worker`, `completed_steps`, `retry_counts` |
| `worker_start` | 某 Worker 开始执行时 | `worker`（节点名） |
| `worker_complete` | 某 Worker 执行完成时 | `worker`, `status`, `summary`, `duration_ms` |
| `worker_retry` | Supervisor 决定重试某节点 | `worker`, `retry_count`（当前第几次） |

---

## 五、前端改动详情

### 5.1 核心理念：从"线性日志"升级为"调度控制台"

**现有问题**：`AgentTerminal` 是滚动文字流，用户无法感知哪个 Agent 在运行、整体调度进度如何。

**目标体验**：

```
┌─────────────────────────────────────────────────────────────────┐
│  🧠 Supervisor Agent   [LIVE ORCHESTRATING]          ● 运行中   │
├─────────────────────────────────────────────────────────────────┤
│  💬 "master_agent 已完成，正在调度资质评估 Worker..."            │
│     （Supervisor 决策气泡 - 打字机效果）                          │
├─────────────────────────────────────────────────────────────────┤
│  Worker 状态矩阵：                                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │ master_agent │  │ strategy_qual│  │strategy_risk │          │
│  │  ✅ 完成      │  │  ⚙️ 执行中...│  │  ⏳ 等待      │          │
│  │  用时 12.3s  │  │  [████░░] 60%│  │              │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
│  ┌──────────────┐  ┌──────────────┐                             │
│  │cost_estimation│  │ writer_agent │                             │
│  │  ⏳ 等待      │  │  🔒 未解锁   │                             │
│  └──────────────┘  └──────────────┘                             │
├─────────────────────────────────────────────────────────────────┤
│  [展开详细日志 ▾]  ← 折叠/展开 AgentTerminal                     │
└─────────────────────────────────────────────────────────────────┘
```

---

### 5.2 [NEW] `frontend/src/components/dashboard/AgentOrchestrator.tsx`

核心 TypeScript 接口设计：

```typescript
interface WorkerStatus {
  name: string;
  label: string;          // 中文显示名
  status: 'waiting' | 'running' | 'success' | 'failed' | 'skipped' | 'locked';
  retryCount: number;     // 已重试次数（上限 MAX_RETRIES=2）
  summary?: string;       // 完成后的执行摘要
  durationMs?: number;    // 执行耗时（毫秒）
}

interface SupervisorState {
  isActive: boolean;
  currentDecision?: string;       // Supervisor 最新决策理由（打字机显示）
  workerStatuses: WorkerStatus[]; // 5个 Worker 的实时状态
}

// 初始 Worker 状态
const INITIAL_WORKERS: WorkerStatus[] = [
  { name: 'master_agent',    label: '元数据提取',  status: 'waiting', retryCount: 0 },
  { name: 'strategy_qual',   label: '资质评估',    status: 'locked',  retryCount: 0 },
  { name: 'strategy_risk',   label: '风险扫描',    status: 'locked',  retryCount: 0 },
  { name: 'cost_estimation', label: '成本测算',    status: 'locked',  retryCount: 0 },
  { name: 'writer_agent',    label: '投标书生成',  status: 'locked',  retryCount: 0 },
];
```

---

### 5.3 Worker 卡片视觉状态规范

| 状态 | 卡片样式 | 图标 | 动画效果 |
|---|---|---|---|
| `waiting` | `border-slate-700 bg-slate-800/50` | ⏳ | 无 |
| `running` | `border-blue-500 bg-blue-900/30 shadow-blue-500/20` | ⚙️ | `border-pulse` + 内部扫光 |
| `success` | `border-emerald-500 bg-emerald-900/20` | ✅ | `scale-in` 入场 |
| `failed` | `border-rose-500 bg-rose-900/20` | ❌ | `shake` 抖动 |
| `skipped` | `border-yellow-600 bg-slate-800/30 border-dashed` | ⏭️ | 无 |
| `locked` | `border-slate-700 bg-slate-900/50 opacity-50` | 🔒 | 无（等依赖解锁） |

**Supervisor 决策气泡**：
- 新决策到来时，气泡从顶部滑入（`translateY` 动画）
- 内容使用**打字机效果**逐字显示 `reasoning` 字段
- 上一条气泡自动灰化缩小（`opacity-30 scale-95`）

---

### 5.4 [MODIFY] `frontend/src/components/UploadBox.tsx`

在 SSE 消息处理中扩展新消息类型解析：

```typescript
if (msgData.agent_log) {
  const log = msgData.agent_log;

  // 现有处理（不变）
  if (onTerminalMessage) {
    onTerminalMessage({ id: `${Date.now()}-${Math.random()}`, ...log });
  }

  // 新增：Supervisor 决策事件
  if (log.type === 'supervisor_decision' && onSupervisorUpdate) {
    onSupervisorUpdate({
      currentDecision: log.reasoning,
      nextWorker:      log.worker,
      completedSteps:  log.completed_steps ?? [],
      retryCounts:     log.retry_counts ?? {},
    });
  }

  // 新增：Worker 开始执行
  if (log.type === 'worker_start' && onWorkerStatusChange) {
    onWorkerStatusChange(log.worker, 'running');
  }

  // 新增：Worker 完成
  if (log.type === 'worker_complete' && onWorkerStatusChange) {
    onWorkerStatusChange(
      log.worker,
      log.status === 'success' ? 'success' : 'failed',
      log.summary,
      log.duration_ms
    );
  }

  // 新增：Supervisor 决定重试
  if (log.type === 'worker_retry' && onWorkerRetry) {
    onWorkerRetry(log.worker, log.retry_count);
  }
}
```

---

### 5.5 [MODIFY] `frontend/src/pages/AnalysisDashboard.tsx`

布局调整：`AgentOrchestrator`（新）并列 `AgentTerminal`（折叠）：

```tsx
{/* 新增 - Supervisor 可视化控制台 */}
<AgentOrchestrator
  isActive={isAnalyzing}
  supervisorDecision={supervisorDecision}
  workerStatuses={workerStatuses}
/>

{/* 现有 - 详细日志（改为可折叠） */}
<details className="mt-4">
  <summary className="cursor-pointer text-sm text-slate-400 hover:text-slate-200 px-2">
    📋 查看详细 Agent 日志...
  </summary>
  <AgentTerminal isAnalyzing={isAnalyzing} messages={terminalMessages} />
</details>
```

---

## 六、完整改动文件清单

### 后端

| 文件路径 | 操作 | 说明 |
|---|---|---|
| `backend/app/agents/state.py` | MODIFY | 新增 `next`, `completed_steps`, `worker_summaries`, `retry_counts` |
| `backend/app/agents/orchestrator.py` | NEW | Supervisor 节点核心逻辑 |
| `backend/app/graph/builder.py` | MODIFY | 线性 DAG → Hub-and-Spoke 拓扑 |
| `backend/app/agents/supervisor.py` | MODIFY | MasterAgent 返回值补充汇报字段 |
| `backend/app/agents/nodes/strategy_agent.py` | MODIFY | 两个节点补充汇报字段 |
| `backend/app/agents/nodes/cost_agent.py` | MODIFY | 补充汇报字段 |
| `backend/app/agents/nodes/writer_agent_node.py` | NEW | 将 `WordGenerator` 包装为 LangGraph 节点 |
| `backend/app/worker/tasks.py` | MODIFY | `emit_agent_log` 扩展新消息类型 |
| `backend/app/graph/execution.py` | MODIFY | 填充（原空文件）|

### 前端

| 文件路径 | 操作 | 说明 |
|---|---|---|
| `frontend/src/components/dashboard/AgentOrchestrator.tsx` | NEW | Supervisor 可视化核心组件 |
| `frontend/src/components/UploadBox.tsx` | MODIFY | SSE 处理扩展，新增消息类型解析 |
| `frontend/src/pages/AnalysisDashboard.tsx` | MODIFY | 引入 AgentOrchestrator，调整布局 |
| `frontend/src/components/dashboard/AgentTerminal.tsx` | MODIFY | 改为可折叠，新增 `worker_retry` 样式 |

### 测试 & 文档

| 文件路径 | 操作 | 说明 |
|---|---|---|
| `backend/tests/unit/test_supervisor_orchestrator.py` | NEW | Supervisor 路由逻辑单元测试 |
| `docs/changelog/2026-07-21.md` | UPDATE | 追加改动记录 |

---

## 七、验证计划

### 自动测试

```bash
conda activate fastapi
cd backend
pytest tests/unit/test_supervisor_orchestrator.py -v
```

**测试场景**：
- 正常流程：Supervisor 按合理顺序调度完所有 Worker
- 跳过场景：某 Worker 失败2次，Supervisor 跳过并继续
- 幂等性：已完成的 Worker 不会被重复调度
- 依赖锁定：`writer_agent` 在前置 Worker 未完成时不会被调度

### 手动验证清单

- [ ] 上传招标文件，前端 `AgentOrchestrator` 面板出现，5 个 Worker 卡片初始为 `waiting`/`locked`
- [ ] `parser_worker` 完成后，`master_agent` 卡片变为 `running`（蓝色发光 + 扫光动画）
- [ ] `master_agent` 完成后，Supervisor 决策气泡从顶部滑入，打字机效果显示 `reasoning`
- [ ] 依次看到 `strategy_qual` / `strategy_risk` / `cost_estimation` 卡片状态切换
- [ ] `writer_agent` 初始为 `locked`，在前三者完成后自动解锁为 `waiting`
- [ ] 某 Worker 失败时，卡片出现 `shake` 抖动动画，Supervisor 可重试（最多2次）
- [ ] 所有完成后，Supervisor 发出 `FINISH`，面板显示"✅ 全部分析完成"

---

## 八、待确认问题（实施前需用户答复）

1. **`AgentOrchestrator` 与 `AgentTerminal` 的关系**：是完全替换，还是并列（上方状态矩阵 + 下方折叠日志）？
2. **`writer_agent` 生成的 Word 文件**：完成后前端是显示**下载按钮**，还是**内嵌预览**？
