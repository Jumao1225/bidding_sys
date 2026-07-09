# 项目待办与演进路线 (TODO List & Roadmap)

这是一个供你手动维护的待办清单。结合当前的架构状态，我已为你重新规划了后续任务优先级。

## 📝 待办事项 (To Do - 高优先级)

- [ ] **真实的文档解析与 OCR 接入 (Doc Parsing & Storage)**
  - 完善 `doc_parser.py` 和 `skills/ocr_skill.py`，支持提取真实大型 PDF 的文本与表格。
  - 接入 MinIO，将用户上传的文件转存至对象存储而不是本地临时文件夹。
- [ ] **真实大模型打通与 Prompt 调优 (LLM & Prompt Tuning)**
  - 去除 `UploadBox.tsx` 和后端大模型服务中的演示 Mock 数据。
  - 针对 `strategy_agent.py` 和 `cost_agent.py`，设计并调优结构化系统提示词 (System Prompt)，确保大模型能稳定吐出匹配的 JSON。
- [ ] **RAG 向量检索接入 (RAG Setup)**
  - 完善数据库设计中预留的 `doc_chunks` 向量表（引入 `pgvector`）。
  - 在大模型接入层实现真实的相似度查询，让前端的 `ChatPanel` 能够基于真实文档内容回答问题。

## 🚀 待办事项 (To Do - 中低优先级)

- [ ] **标书自动生成与导出 (Word Generation)**
  - 完善 `writer_agent.py`，利用前面各个 Agent 收集到的结论，自动套用 Word 模板并支持用户在前端一键下载草案。
- [ ] **用户权限与多租户 (Auth & Multi-tenancy)**
  - 在 `api/` 层加入真正的 JWT 鉴权。
  - 确保底层数据访问严格遵循 `tenant_id` 隔离（参考已通过测试的 `test_db_models.py`）。

## 🚧 进行中 (In Progress)
- [ ] **全链路沙盒联调**：即将把真实的 LLM Key 填入 `.env` 并做真实文件链路测试。

## ✅ 已完成 (Done)
- [x] **数据库层连通与基础设施搭建 (Database Integration)**：摒弃了开发环境的 SQLite 妥协方案。通过 `docker-compose` 搭建了原生的 PostgreSQL 与 Redis 容器，配置了严格拒绝退化的 `.env` 鉴权机制，并使用 Alembic `upgrade head` 成功初始化了所有的 DDD 多租户表结构。
- [x] **架构设计与技术栈选型**：确立 FastAPI + React + Vite 骨架，并完成了 DDD 变体分层架构设计。
- [x] **多智能体工作流重构**：引入 LangGraph 将散乱逻辑重构为 `BiddingState` 状态图，并使用 `@tool` 简化技能库。
- [x] **异步处理与 SSE 流式推送**：集成 Celery 处理长耗时任务，并在前端实现原生 `EventSource` 的各阶段流式进度订阅。
- [x] **Epic Design 旗舰视觉交互**：全面重构前端，加入毛玻璃 (Glassmorphism)、动态光晕背景 (Mesh Gradients)、渐变组件与细致入微的微动画 (Micro-animations)。
- [x] **测试隔离层重构与验证**：规范化 `backend/tests/` 目录，抽离假数据至 `fixtures/`，通过 `httpx.AsyncClient` 实现异步接口测试，核心链路测试 **100% Pass**。
- [x] **LLM 配置与容错降级**：通过 `tenacity` 实现了大模型调用的指数退避与自动重试机制。
