# 智能投标系统项目待办与演进路线 (V2.0 TODO List & Roadmap)

该文档记录了基于 V2.0“确定性流水线控制 + 大模型受控节点提取 + 人机协同最终决策”架构的后端核心链路落地步骤与历史完成事项。

## 📝 待办事项 (To Do)

### 阶段一：数据基石 - 解析引擎进阶 (Parser Worker)
- [ ] **集成 MinerU 深度解析**
  - [ ] 集成开源的 `MinerU` 进行扫描件与复杂版面的本地部署解析，弥补 Docling 在重度图文混排扫描件上的不足。
- [ ] **视觉大模型 (VLM) 兜底提取**
  - [ ] 当检测到极其复杂的扫描版跨页表格（如造价表、参数偏离表）时，自动截取该页图片，直接调用多模态视觉模型（如 Qwen-VL, GPT-4o）强制输出高精度的 Markdown 表格。

### 阶段二：单兵作战 - 专业 Agent 与 Worker 节点打磨
- [ ] **Business & Qual Agent (商务与资质专家)**
  - [ ] 接入企业资产库 (Asset_Qualification, Asset_Employee, Asset_ProjectCase)。
  - [ ] 根据 Master Agent 提取的“硬性资质”，自主调用查询技能匹配公司资质、人员和历史业绩。
- [ ] **Cost Agent (报价计算专家)**
  - [ ] 接入主材和辅材的基础价格数据库。
  - [ ] 结合 Master Agent 提取的 `budget_limit`，实现动态报价平衡与利润率反算，确保不超限价。
- [ ] **Tech & Service Worker (技术与售后流水线)**
  - [ ] 利用高级 RAG 检索内部技术规范文档，结合痛点工况（如“彩钢瓦加固”）生成专项技术方案。
  - [ ] 将标书服务要求转化为标准格式化承诺书与培训大纲。
- [ ] **Review Engine (合规与红线非 AI 引擎)**
  - [ ] 编写纯代码逻辑，进行废标词扫描、单一品牌强制校验。
  - [ ] 实现资金红线拦截（如总价突破限价立即打回）。

### 阶段二：神经中枢 - LangGraph 动态路由与人机干预
- [ ] **【重点演进】Master Agent 动态路由 (Conditional Edges)**
  - [ ] 废弃目前的串行“单行道”，实现 Master Agent 提取元数据后的任务并发下发 (Fan-out) 与按需跳过。
  - [ ] 赋予 Master Agent 真正的分发权，基于提取到的标书特征（如是否含报价、痛点类型）决定激活下游哪些专业 Agent。
- [ ] **人工审批卡点 (Human-in-the-loop)**
  - [ ] 在 LangGraph 核心环节（如价格超标、疑似废标项）设置 `Interrupt` 中断点。
  - [ ] 暴露 `Resume` API，允许前端人工修改确认后恢复工作流流转。

### 阶段三：前端深度联动 (UI Integration)
- [ ] **溯源联动高亮**
  - [ ] 改造前端文档渲染器（如 `LocalDocxRenderer`）。
  - [ ] 联调后端返回的风险项 JSON，实现点击前端卡片，文档自动滚动高亮到对应切片。
- [ ] **审批流面板**
  - [ ] 开发独立的审批卡点模态框，供用户确认或驳回 AI 生成的响应内容。

---

## ✅ 已完成 (Done)

### 架构与基础设施 (Architecture & Infra)
- [x] **V2.0 架构设计落地**：确立了“DB First”、“人工负责决策”、“万物皆可溯源”的底线原则 (2026-07-13)。
- [x] **多智能体工作流重构**：引入 LangGraph 将散乱逻辑重构为 `BiddingState` 状态图，并组装了基础的顺序流转 Pipeline (`builder.py`)。
- [x] **数据库与异步基建**：原生 PostgreSQL + Redis 容器化，Alembic DDD 模型初始化，Celery 异步长耗时推理，FastAPI SSE 流式进度订阅。

### 数据基石与解析引擎 (Data & Parsing)
- [x] **智能文档解析 (Docling)**：完成基于语义和版面的复杂 PDF/Word 剥离提取。
- [x] **章节级巨型分块 (Chapter-based Chunking)**：废弃碎片化切分，通过 Aggregator 将文本完美按章切块，单块容量可达 3000 字。
- [x] **防误伤状态机与时间戳测序**：通过强力正则兜底修正 Docling 漏认标题 Bug，过滤误切分目录，并通过时序叠加完美解决数据库可视化排序混乱。
- [x] **提取全局目录大纲 (TOC)**：自动提炼文档骨架入库，赋予大模型无与伦比的全局导航视角。

### 高级检索与总控大脑 (Retrieval & Master Agent)
- [x] **高级 RAG 混合检索引擎**：实现 Query Expansion (多路查询重写) + 向量余弦检索 + ILIKE 关键字精准模糊匹配。
- [x] **基于章节的全量上下文召回 (Section-Based Context)**：打破物理滑窗限制，命中切片后自动拉取同章节的所有切片拼接，实现近 6 万字的“按章召回”，彻底消灭上下文碎片化。
- [x] **Master Agent (总控智能体) 落地**：独立节点读取大纲与前 25000 字，利用 Tool-Calling 深挖全篇痛点，精准提炼出项目编号、预算限价、硬性资质等四大元数据并落库 `parsed_metadata`。
