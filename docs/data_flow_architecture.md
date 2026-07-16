# 策略智能体数据流转架构说明

本文档详细记录了策略智能体（Strategy Agent）产出的高阶分析结论在系统中的生产、存储与回显的完整数据链路。

## 1. 履约盘点 (Compliance Check)

**对应字段:** `qualifications_analysis`

### 一、 数据来源机制 (生产阶段)
核心逻辑位于 `backend/app/agents/nodes/strategy_agent.py` 的 `analyze_qualifications_node` 方法。
- **复用主控数据 (DB First)**: 优先读取主控智能体 (Master Agent) 存入 `Document.parsed_metadata` 的 `hard_qualifications`（核心硬性资质列表）。
- **RAG 兜底扫盲**: 调用向量数据库，使用高优先级的资质类关键字（如“投标人资格要求”、“资质”、“业绩”、“人员”）整章拉取相关原文片段，防止主控智能体遗漏。
- **己方底牌映射**: 获取系统配置的本公司资质条件（`company_quals`）。
- **模型推断**: 将标书要求与己方条件提交给大模型，扮演“资深投标经理”进行三级状态的客观逻辑评估。

### 二、 字段结构与存储 (落盘阶段)
在 `backend/app/worker/tasks.py` 任务结束前，大模型输出的 JSON 报告会被序列化，直接写入 `documents` 表格内的 `parsed_metadata` JSONB 字段。
核心输出字段包括：
- `match_score`: 综合资质匹配度 (0-100)。
- `items`: 逐条盘点明细数组，包含 `requirement` (要求简述)、`status` (匹配状态：可以做到/努力可做到/做不到)、`reason` (大模型给出的判定原因)、`exact_quote` (原文一字不差的引用词，是前端锚点高亮的依据)。

### 三、 历史回显与前端渲染
1. **API 拉取**: 点击历史记录时，前端调用 `GET /api/v1/documents/{doc_id}/result`。后端的 `document.py` 接口会将深埋在 `parsed_metadata` 里的 `qualifications_analysis` 数据重新提取，并入主包裹返回。
2. **状态初始化**: 前端 `AnalysisDashboard.tsx` 将拉取到的数据作为 `initialResult` 注入 `UploadBox` 组件，使组件跳过“拖拽上传”的初始状态，直接激活阅读器分屏模式。
3. **UI 渲染**: `UploadBox` 内部组件直接读取 `result.qualifications_analysis.items` 数组渲染至右侧“履约盘点”标签页，并用正则表达式扫描左侧 Markdown 文本，匹配 `exact_quote` 以实现红/橙/绿的高亮底纹效果。

---

## 2. 风险提示 (Risk Warnings)
*(数据来源架构梳理中，待后续补充接入...)*
