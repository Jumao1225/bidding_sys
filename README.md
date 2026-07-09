# 智能投标辅助系统 (AI Bidding Assistant)

这是一个利用 AI 技术深度解析招标文件并辅助撰写投标书的 Web 应用程序。不仅作为独立的效率工具，更是面向未来的完整“企业级多智能体协同 (Agentic Workflow) 平台”的核心引擎。

## 🌟 核心特性

- **Epic Design 极致视觉交互**：前端采用现代 SaaS 旗舰级视觉规范，全体系 Glassmorphism 毛玻璃质感、流体渐变环境与细腻微交互。
- **流式异步解析引擎**：后端采用 Celery 作为分布式队列调度，结合 SSE (Server-Sent Events) 向前端实时反馈各阶段多智能体的思考进度。
- **LangGraph 多智能体工作流**：将原本线性刻板的逻辑重塑为灵活的有向状态图，各专业 Agent（资质比对、风险扫描、成本核算）协同作战。
- **高可用大模型底座**：技能库由统一轻量的 `@tool` 组成，核心调用嵌有 `Tenacity` 指数退避自动重试，无惧网络波动。

## 🚀 核心架构与目录结构

本项目采用**高内聚、低耦合**的模块化设计，完美融合了**领域驱动设计 (DDD)** 思想。最新代码结构如下：

```text
bidding_sys/
├── docker-compose.yml         # 编排前后端、PostgreSQL 与 Redis
├── README.md
├── docs/                      # 核心设计文档库 (Architecture, Database, Changelog)
│
├── frontend/                  # React + Vite 前端 (Epic TailwindCSS 设计)
│   ├── package.json
│   └── src/
│       ├── main.tsx           
│       ├── App.tsx            # 全局工作台视图 (Cinematic Banner, 悬浮浮窗)
│       ├── index.css          # 全局样式 (Inter 字体, 极光渐变背景, 微动画)
│       ├── components/        # 核心交互组件 (SSE 流式上传、成本面板、AI 对话)
│       └── layouts/           # 页面布局 (暗色玻璃态侧边栏)
│
└── backend/                   # Python FastAPI 后端 (DDD 架构)
    ├── tests/                 # 测试隔离层
    │   ├── conftest.py
    │   ├── unit/              # Agent 节点单元测试
    │   ├── integration/       # 数据库聚合测试
    │   ├── api/               # 纯异步接口 HTTPX 测试
    │   └── fixtures/          # 解耦的假数据源 (Mock JSON)
    │
    └── app/                   # 核心业务
        ├── main.py            # FastAPI 启动入口
        ├── core/              # 核心配置 (Config, Security, Celery 初始化)
        ├── db/                # 数据访问层 (Models, Session, CRUD)
        ├── schemas/           # 数据校验层 (Pydantic DTOs)
        ├── api/               # 接入层 (路由控制与 SSE 接口)
        ├── worker/            # 异步任务层 (Celery Tasks)
        ├── graph/             # [★ 核心] LangGraph 状态图的组装与编译
        ├── agents/            # [★ 核心] 多智能体
        │   ├── state.py       # 全局 TypedDict (BiddingState)
        │   └── nodes/         # 拆解后的具体执行域 (strategy_agent, cost_agent 等)
        └── skills/            # [★ 核心] 沉淀的专用技能库 (@tool 插件)
```

## 🛠️ 开发与运行指南

### 1. 启动后端 (Python FastAPI)
本环境依赖 `fastapi` 的 conda 环境，且需要预先配置好 Redis（用于 Celery 和 SSE 通信）。

```bash
conda activate fastapi
cd backend
pip install -r requirements.txt
# 启动 Celery Worker
celery -A app.core.celery_app worker --loglevel=info -P solo
# 启动 API 服务器
uvicorn app.main:app --reload
```

### 2. 数据库迁移与表结构管理 (Alembic)
系统采用 PostgreSQL 并通过 Alembic 进行结构追踪。当您修改了 `app/db/models/` 下的 Python 模型后，只需执行标准的“三步走”工作流即可同步数据库：

```bash
cd backend
# 1. 对比模型变更，自动生成带有描述的迁移脚本
python -m alembic revision --autogenerate -m "描述您的更改，例如 add_age_to_user"
# 2. 将迁移脚本中的 SQL 真正应用到 PostgreSQL
python -m alembic upgrade head

# 附加：如果刚才升级错了想要撤销回退一个版本，可执行：
python -m alembic downgrade -1
```

### 3. 执行自动化测试 (100% 覆盖核心流)
系统集成了异步支持与数据解耦的单元测试：
```bash
cd backend
python -m pytest tests
```

### 3. 启动前端 (React Vite)
```bash
cd frontend
npm install
npm run dev
```

## 📈 演进路线
- 2026-07-09: **Epic Design 与工作流重构**（前后端彻底拥抱流式 SSE 与 LangGraph 智能体网络）。
- 后续规划: 引入真实数据库持久化、接入 RAG 向量检索与 `pgvector` 以强化 Chat 问答能力。
