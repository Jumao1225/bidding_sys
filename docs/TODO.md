# 智能投标系统项目待办与演进路线 (TODO List & Roadmap)

该文档记录了基于 Multi-Agent 架构的后端核心链路落地步骤与历史完成事项。

## 📝 待办事项 (To Do)

### 阶段一：数据基石 - Extractor Agent (拆解智能体) 搭建
- [x] **文件解析模块开发**
  - [x] 编写 PDF 解析服务（基础文本提取使用 `Docling` 和 `PyMuPDF`）。
  - [x] 编写 Word 解析服务（使用 `Docling` 统一处理）。
  - [ ] 集成开源的 `MinerU` 进行扫描件与复杂版面的本地部署解析（目前已写好路由架构与桩代码，待接入实体模型）。
  - [ ] 引入视觉大模型 (VLM) 兜底：当检测到极其复杂的扫描版跨页表格（MinerU 效果不佳时），截取该页图片，直接调用多模态视觉模型（如 Qwen-VL, GPT-4o）强制输出 Markdown 表格。
- [x] **语义切片与元数据处理**
  - [x] 使用 `LangChain` 实现基于语义和逻辑结构的切片 (Chunking)。
  - [x] 为文本块打入追踪溯源的核心 Metadata (`page_num`, `section_title`, `content_type`)。
- [x] **向量数据库打通**
  - [x] 完善 `DOC_CHUNK` 表模型。
  - [x] 接入 Embedding 模型，实现 Chunk 的批量向量化入库（**PostgreSQL + pgvector**，并使用本地魔搭 `BGE-M3` 懒加载）。

### 阶段二：单兵作战 - 专家 Agent (快车道 API) 开发
- [ ] **Compliance Agent (排雷智能体)**
  - [ ] 编写核心 System Prompt，强化对“无星号”条款的语义识别（检索“必须”、“违约金”等强限制性词汇，调用 LLM 推理判定实质性壁垒）。
  - [ ] 开发双路召回检索（Hybrid Search），提取高危段落。
  - [ ] 提供无状态的独立 FastAPI 路由（如 `/api/analyze/risk`），供前端直接调用。
- [ ] **Strategy Agent (策略与计分智能体)**
  - [ ] 提取打分表、生成资质匹配红绿灯。
- [ ] **Writer Agent (标书撰写智能体)**
  - [ ] 自动起草偏离表与标书草稿。
- [ ] **避坑指南知识库 [低优先级 / 延后]**
  - [ ] 梳理一份内部的《隐蔽陷阱避坑指南》（例如不合理的付款条件、资质壁垒），作为后续 RAG 的增强参考。

### 阶段三：神经中枢 - 多智能体编排 (LangGraph)
- [ ] **状态机与工作流设计**
  - [ ] 在 LangGraph 中定义统一的 State (Blackboard) 数据结构。
  - [ ] 串联上述专家 Agent，形成标准的审批与撰写流水线。
- [ ] **Supervisor Agent (智能主控)**
  - [ ] 编写意图识别模型，将底层 Agent 注册为可调用的 Tools。
  - [ ] 提供自然语言处理接口（慢车道 `/api/chat/supervisor`）。
- [ ] **异步调度与 SSE 流式推送**
  - [ ] 将耗时任务放入 Celery 中执行后台推理。
  - [ ] 搭建 FastAPI 的 SSE 接口，实时向前端推送 Agent 思考状态。

### 阶段四：前后端大联动 (UI Integration)
- [ ] **溯源联动高亮**
  - [ ] 改造前端文档渲染器（如 `LocalDocxRenderer`），暴露页面/章节跳转的 API。
  - [ ] 联调后端返回的风险项 JSON，实现点击前端卡片，文档自动滚动高亮对应条款。
- [ ] **智能对话与状态面板**
  - [ ] 联调 SSE 接口，前端呈现 Agent 正在后台运作的步骤树。
  - [ ] 测试快车道与慢车道（自然语言聊天）的双轨运行稳定性。

---

## ✅ 已完成 (Done)

- [x] **架构设计探讨与落地方案确认**：完成了基于 Multi-Agent、LangGraph 的混合路由架构设计，确认了无星号排雷逻辑、视觉模型增强方案及数据库选型 (2026-07-10)。
- [x] **数据库层连通与基础设施搭建 (Database Integration)**：摒弃了开发环境的 SQLite 妥协方案。通过 `docker-compose` 搭建了原生的 PostgreSQL 与 Redis 容器，配置了严格拒绝退化的 `.env` 鉴权机制，并使用 Alembic `upgrade head` 成功初始化了所有的 DDD 多租户表结构。
- [x] **架构设计与技术栈选型**：确立 FastAPI + React + Vite 骨架，并完成了 DDD 变体分层架构设计。
- [x] **多智能体工作流重构**：引入 LangGraph 将散乱逻辑重构为 `BiddingState` 状态图，并使用 `@tool` 简化技能库。
- [x] **异步处理与 SSE 流式推送**：集成 Celery 处理长耗时任务，并在前端实现原生 `EventSource` 的各阶段流式进度订阅。
- [x] **Epic Design 旗舰视觉交互**：全面重构前端，加入毛玻璃 (Glassmorphism)、动态光晕背景 (Mesh Gradients)、渐变组件与细致入微的微动画 (Micro-animations)。
- [x] **测试隔离层重构与验证**：规范化 `backend/tests/` 目录，抽离假数据至 `fixtures/`，通过 `httpx.AsyncClient` 实现异步接口测试，核心链路测试 **100% Pass**。
- [x] **LLM 配置与容错降级**：通过 `tenacity` 实现了大模型调用的指数退避与自动重试机制。
