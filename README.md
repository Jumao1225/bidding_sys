# 智能投标辅助系统

智能投标辅助系统（AI Bidding Assistant）是一个面向招投标业务的全栈 Web 应用，负责解析招标文件、提取结构化要求、生成工程量/BOM 清单、辅助成本核算，并通过多智能体协作完成标书填报与审计。

项目当前采用 React + Vite 前端、FastAPI 后端、PostgreSQL + pgvector 数据库、Redis 消息中间件，以及 LangGraph 多智能体工作流。

## 功能概览

- **招标文件解析**：支持 PDF、DOCX 等文件的上传、解析、预览和原文下载；可接入 Docling、MinerU 及视觉模型处理复杂版式。
- **结构化信息提取**：按工程清单、资格条件、评标办法、财务要求、工期要求等领域提取要求，并保留来源证据和上下文。
- **工程量与 BOM 分析**：识别表格内分组、表格外分区、跨分页续表、父子层级和跨行合并单元格，支持数量、单位、规格及关键参数整理。
- **成本核算与导出**：结合价格参考库生成成本分析；前端展示层级清单，并导出 DOCX 和 XLSX。导出时支持表格外分区、表格内分组及无分组模式。
- **标书模板与自动填报**：上传并绑定外部 Word 模板，提取模板章节和填报槽位；Agent 执行可填字段，`needs_writing` 章节明确保留为人工撰写待办。
- **多智能体协作**：基于 LangGraph 编排解析、资格、策略、成本、撰写和审计 Agent；当前由 FastAPI 内部线程/线程池执行长任务，通过 Redis Pub/Sub + SSE 实时反馈任务进度和 Agent 日志。
- **审计与可观测性**：记录模型调用、工具调用、Token 消耗、章节填报结果和 Supervisor 终审结果，支持从前端查看审计报告。
- **标书打分实验室**：支持评分文件上传、评审条目管理、分类评分、结果查询和 Ragas 评测。
- **企业与业务数据管理**：提供登录认证、多租户隔离、企业档案、资质库、价格参考库和管理员模型配置页面。
- **Word 工具链**：提供目录、修订、批注、隐私清洗等 DOCX 调试和处理能力；标书填报链路通过 OfficeCLI 查询 Word DOM 并执行受控写盘。

## 业务流程

```text
上传招标文件
    ↓
文档解析与原文证据保留
    ↓
领域 Agent 提取：工程量 / 资格 / 评标 / 财务 / 工期
    ↓
成本核算、BOM 层级整理与前端审阅
    ↓
绑定 Word 模板并提取填报章节
    ↓
章节 Agent 填报 → Supervisor 审计
    ↓
人工补写待办确认 → 下载 DOCX / XLSX / 审计结果
```

## 系统架构

```text
bidding_sys/
├── docker-compose.yml             # PostgreSQL(pgvector) 与 Redis（SSE 消息）
├── .env.example                   # 环境变量模板
├── README.md
├── docs/                          # 设计文档、需求文档与变更日志
│   └── changelog/YYYY-MM-DD.md
├── models/                        # 本地 Embedding 模型目录
├── output/                        # 生成的导出文件
├── uploads/                       # 根目录兼容/辅助文件目录
├── backend/
│   ├── uploads/                   # 当前后端主流程的上传、模板和草稿目录
│   ├── outputs/                   # 后端生成的上下文日志等输出目录
│   ├── app/
│   │   ├── main.py                # FastAPI 入口与 /health
│   │   ├── api/                   # 路由层及 SSE 接口
│   │   ├── agents/                # 多智能体、节点、工具与审计流程
│   │   ├── graph/                 # LangGraph 构建与执行
│   │   ├── mcp/                   # OfficeCLI MCP Server/Client 封装
│   │   ├── middleware/            # FastAPI 中间件
│   │   ├── core/                  # 配置、日志、安全与沙箱
│   │   ├── db/                    # SQLAlchemy 模型、会话与数据访问
│   │   ├── schemas/               # Pydantic 请求/响应模型
│   │   ├── services/              # 解析、提取、成本、填报、导出等业务服务
│   │   ├── utils/                 # 通用业务辅助工具
│   │   ├── uploads/               # 应用包内的兼容目录
│   │   ├── worker/tasks.py        # 分析任务、进度发布与 Agent 日志工具
│   │   └── skills/                # 可复用的领域技能
│   ├── alembic/                   # 数据库迁移
│   ├── requirements.txt
│   └── tests/
│       ├── unit/                  # 单元测试
│       ├── integration/           # 集成测试
│       ├── api/                   # 异步 API 测试
│       └── fixtures/              # 测试数据
└── frontend/
    ├── src/
    │   ├── assets/                # 静态资源
    │   ├── pages/                 # 首页、分析、成本、填报审计、打分等页面
    │   ├── components/            # 上传、成本表、模板面板、Agent 终端等组件
    │   ├── contexts/              # 登录与全局状态上下文
    │   ├── layouts/               # 主布局
    │   ├── api/                   # 前端 API 封装
    │   └── utils/                 # 导出、文本归一化、错误处理等工具
    └── package.json
```

## 本地启动

### 运行前提

- Conda，并创建可用的 `fastapi` 环境。
- Docker Desktop，用于启动 PostgreSQL 和 Redis。
- Node.js 与 npm，用于启动前端。
- 可访问的 OpenAI 兼容大模型服务；复杂文档场景可额外配置 MinerU、VLM。

项目后端命令约定在 `fastapi` conda 环境中执行：

```powershell
conda activate fastapi
```

### 1. 配置环境变量

```powershell
Copy-Item .env.example .env
```

复制模板后仍需检查并填写数据库配置。使用本地 Docker 时，`.env.example` 中的默认地址与 `docker-compose.yml` 的 PostgreSQL 服务一致；使用外部 PostgreSQL 时，必须提前创建数据库和账号并替换 `DATABASE_URL`。项目不支持退化到 SQLite。

至少检查并填写以下配置：

| 变量 | 作用 |
| --- | --- |
| `DATABASE_URL` | PostgreSQL 连接地址，必须使用 `postgresql://` |
| `REDIS_URL` | SSE 和后台任务进度消息地址 |
| `OPENAI_API_KEY` | OpenAI 兼容模型密钥 |
| `OPENAI_API_BASE` | 模型服务地址，例如 `https://api.openai.com/v1` |
| `LLM_MODEL_NAME` | 默认文本模型名称 |
| `ALI_VLM_API_KEY` / `LOCAL_VLM_API_KEY` | 可选，视觉模型密钥 |
| `MINERU_API_TOKEN` | 可选，MinerU 在线解析服务令牌 |

使用 DeepSeek 结构化提取时，可通过 `DEEPSEEK_MAX_OUTPUT_TOKENS` 和 `DEEPSEEK_THINKING_ENABLED` 调整输出上限及思考模式。`SKIP_BID_FILLER=true` 仅适合调试时跳过长流程，生产环境应保持为 `false`。

### 2. 启动基础设施

```powershell
docker compose up -d postgres redis
```

确认服务健康后，在后端目录安装依赖并执行迁移：

```powershell
conda activate fastapi
Set-Location backend
pip install -r requirements.txt
python -m alembic upgrade head
```

### 3. 启动 FastAPI

在一个终端中执行：

```powershell
conda activate fastapi
Set-Location backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

后端地址：

- 健康检查：<http://127.0.0.1:8000/health>
- Swagger：<http://127.0.0.1:8000/docs>
- OpenAPI JSON：<http://127.0.0.1:8000/openapi.json>

当前分析和标书填报流程由 FastAPI 进程内部的后台线程或线程池执行，不需要单独启动 Celery Worker。`backend/app/core/celery_app.py` 仍保留为 Celery 配置模块，但不是当前本地运行的必需进程。

Redis 仍然需要启动，因为分析进度、Agent 日志和 SSE 订阅依赖 Redis Pub/Sub。

### 4. 启动前端

```powershell
Set-Location frontend
npm install
npm run dev
```

默认访问地址：<http://127.0.0.1:5173>。前端通过 `VITE_API_BASE_URL` 指定后端地址；未配置时会自动使用当前主机的 `8000` 端口。

### 5. 服务器部署启动（Linux）

服务器上使用项目自带的 Python 虚拟环境 `.venv312` 启动后端，不使用 Conda。以下命令假设项目位于 `~/opt/bidding_sys`，后端和前端分别在两个终端中启动。

先确认 PostgreSQL、Redis 和 OfficeCLI 已按前文完成配置，并确认服务器防火墙或安全组已按需开放 `8000`、`5173` 端口。

后端终端：

```bash
cd ~/opt/bidding_sys/backend/
source ../.venv312/bin/activate
PYTHONPATH=. uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

前端终端：

```bash
cd ~/opt/bidding_sys/frontend/
npm run dev
```

如果服务器尚未安装前端依赖，首次启动前先在 `frontend` 目录执行 `npm install`。启动后，浏览器访问 `http://服务器IP:5173`；后端健康检查地址为 `http://服务器IP:8000/health`。前端 Vite 已配置为监听 `0.0.0.0`，并通过 `VITE_API_BASE_URL` 或当前访问主机的 `8000` 端口连接后端。

## OfficeCLI 文档处理链路

OfficeCLI 是项目标书填报流程使用的外部 Office 文档操作引擎。后端由 `OfficeCLIService` 调用本机 `officecli` 可执行文件；Supervisor 通过 `backend/app/mcp/office_cli_client.py` 调用 MCP 封装，章节 Worker 则使用 `backend/app/agents/tools/office_cli_agent_tools.py` 的 Agent 工具。两条路径最终共享 `backend/app/services/office_cli_service.py` 的底层实现。

### 主要用途

- 查询 Word 文档的段落、表格和完整 DOM 结构，定位 `/body/p[N]`、`/body/tbl[N]` 等物理路径。
- 按 JSON 指令批量原位替换段落或单元格内容，减少多次写盘造成的格式风险。
- 追加表格行、批量填充表格二维数据，并保护表头、处理模板空白行和序号列。
- 将键值数据合并到 Word 模板中的 `{{占位符}}`，生成新的 DOCX 文件。
- 在资质章节的指定节点插入证书图片；写入前校验原文锚点，避免图片错插。
- 当 OfficeCLI 写盘遇到节点路径或文件占用问题时，自动清理残留进程、重试，并对部分文本提案回退到 `python-docx` DOM 写盘。

### Agent 工具

标书填报 Agent 可使用以下 OfficeCLI 工具：

| 工具 | 用途 |
| --- | --- |
| `officecli_query_structure` | 查询 DOCX 段落、表格或全部 DOM 结构 |
| `officecli_write_slot_value` | 原位写入单个文本槽位 |
| `officecli_batch_write_slots` | 批量写入多个文本槽位 |
| `officecli_batch_fill_sentence` | 批量替换长句或段落 |
| `officecli_fill_table_rows` | 覆写/追加表格数据行并清理多余空行 |
| `officecli_add_table_row` | 追加一行并按表格格式填充单元格 |
| `officecli_insert_image` | 在指定 Word 节点插入资质证明图片 |

### 安装与检查

OfficeCLI 不由 `requirements.txt` 或 `npm install` 安装，需要在运行后端的主机上单独安装。**本项目硬性要求只能使用 OfficeCLI `1.0.145`，其他版本不得接入。** Linux 和 Windows 都应直接下载官方 `v1.0.145` 发布二进制，不要使用会追踪最新版本的安装器。

```bash
mkdir -p "$HOME/.local/bin"
curl -fL https://github.com/iOfficeAI/OfficeCLI/releases/download/v1.0.145/officecli-linux-x64 -o "$HOME/.local/bin/officecli"
chmod +x "$HOME/.local/bin/officecli"
export PATH="$HOME/.local/bin:$PATH"
test "$(officecli --version)" = "1.0.145" || { echo "OfficeCLI 版本必须为 1.0.145" >&2; exit 1; }
```

Windows x64 使用 PowerShell 下载 `https://github.com/iOfficeAI/OfficeCLI/releases/download/v1.0.145/officecli-win-x64.exe` 到 `%LOCALAPPDATA%\OfficeCLI\officecli.exe`，Windows ARM64 使用 `officecli-win-arm64.exe`；Linux ARM64 使用 `officecli-linux-arm64`。下载地址中的 `v1.0.145` 是版本锁定的一部分，不得替换成 `latest` 或其他版本。

安装完成后必须通过 `officecli --version` 做等值校验。仓库没有通过依赖文件管理 OfficeCLI，因此不得使用未锁版本的 npm、Homebrew 或最新版本安装脚本替代上述二进制安装方式。安装渠道必须保持单一。

注意：`backend/app/skills/officecli/fix-officecli-env.sh` 在发现已有 `officecli` 且未设置 `OFFICECLI_REFRESH_BINARY=1` 时会复用现有二进制；但在缺少二进制或启用刷新时会调用未锁版本的安装脚本，不能保证安装出 `1.0.145`。因此它不能作为本项目的严格版本安装器。当前 skill 的部分检查命令与 1.0.145 的 CLI 命令面存在差异，最终验收以 `officecli --version` 等值校验和 OfficeCLI DOCX 回归为准。

项目会按以下顺序查找：PATH 中的 `officecli`，以及 Windows 的 `%LOCALAPPDATA%\\OfficeCLI\\officecli.exe`。该查找逻辑位于 `backend/app/services/office_cli_service.py`。

```powershell
Get-Command officecli
officecli --version
officecli --help
```

如果命令不可用，请参考项目内的 [OfficeCLI Skill](backend/app/skills/officecli/README.md) 和检查脚本。当前 1.0.145 不支持 `whoami`、`doctor` 和 `config runtime`，不要将这些旧命令作为本项目的必检项；也不得通过升级到其他版本来绕过 `1.0.145` 版本锁定。

### 运行方式

正常启动 FastAPI 后，标书填报 Agent 会在同一后端进程内调用 OfficeCLI，不需要手动启动 MCP Server。若需要为外部 MCP 客户端提供 stdio 服务，可在 `backend` 目录执行：

```powershell
conda activate fastapi
python -m app.mcp.office_cli_server
```

OfficeCLI 相关底层命令包括 `create`、`query`、`batch`、`close` 和 `merge`；具体参数以本机 `officecli --help` 为准。

## 主要 API 分组

所有业务 API 默认挂载在 `/api/v1` 下，完整参数和响应格式以 Swagger 为准。

| 分组 | 前缀 | 用途 |
| --- | --- | --- |
| 分析 | `/api/v1/analysis` | 文件上传、领域提取、成本分析、BOM DOCX/XLSX 导出 |
| 文档 | `/api/v1/documents` | 文档列表、原文下载、结果查询和删除 |
| 实时任务 | `/api/v1/sse` | 订阅后台任务进度和 Agent 日志 |
| 标书填报 | `/api/v1/bidding` | 模板上传、模板绑定、章节提取、自动/人工填报和审计 |
| 标书打分 | `/api/v1/bid-scorer` | 评分文件、评分结果和 Ragas 评测 |
| 企业与资质 | `/api/v1/company`、`/api/v1/qualifications` | 企业档案和资质库管理 |
| 业务数据 | `/api/v1/business` | 价格参考库管理 |
| 认证与管理 | `/api/v1/auth`、`/api/v1/admin` | 登录、租户、用户和模型配置 |
| 文档工具 | `/api/v1/docx`、`/api/v1/mineru` | DOCX 调试及 MinerU 解析能力 |

统一响应通常包含 `code`、`message` 和 `data` 字段；前端请求封装会自动带上 `bidding_token` Bearer Token。

## 测试与质量检查

后端：

```powershell
conda activate fastapi
Set-Location backend
python -m pytest tests
```

按目录运行专项测试：

```powershell
python -m pytest tests/unit
python -m pytest tests/api
python -m pytest tests/integration
```

前端：

```powershell
Set-Location frontend
npx vitest run
npm run lint
npm run build
```

前端测试位于 `frontend/tests/`，后端测试严格按 `unit/`、`integration/`、`api/` 和 `fixtures/` 分层。OfficeCLI 相关回归测试可单独运行：

```powershell
conda activate fastapi
Set-Location backend
python -m pytest tests/unit/test_office_cli_mcp.py tests/unit/test_bid_filler_worker.py
```

涉及文档解析、LLM 或导出逻辑时，建议同时运行对应专项测试和 `git diff --check`。

## 本地模型与文件目录

`backend/app/services/llm_service.py` 会查找项目根目录下的 `models/bge-m3` 作为本地 Embedding 模型。模型不存在时，系统会记录提示；如需下载，可按项目根目录 `download_model.py` 的逻辑准备模型文件。

当前后端主流程的上传和生成文件主要写入 `backend/uploads/` 及其子目录，包括 `tenders/`、`bids/`、`templates/`、`qualifications/`、`drafts/`、`temp_mineru/`、`mineru_output/`、`docx_output/` 和 `docling_output/`；后端 Agent 上下文日志及辅助输出主要写入 `backend/outputs/`，其中包括 `human_fill_results/` 和 `scratch/`。仓库中的根目录 `uploads/`、`output/` 仍作为兼容或辅助目录存在，但不是当前后端主流程的默认落盘位置。部署时应为实际使用的目录配置持久化存储和访问权限。不要将真实 API Key、投标文件或企业数据提交到版本库。

## 相关文档

- [需求文档](docs/README_REQUIREMENT.md)
- [Agent 记忆与演化设计](docs/AGENT_MEMORY_AND_EVOLUTION_DESIGN.md)
- [Agent 升级计划](docs/AGENT_UPGRADE_PLAN.md)
- [变更日志](docs/changelog/)

每次代码、配置、Prompt、测试或文档改动，都应在 `docs/changelog/YYYY-MM-DD.md` 追加可追踪记录。
