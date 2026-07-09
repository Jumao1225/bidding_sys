# 智能投标系统 - 数据库设计文档 (Database Design)

本文档记录了智能投标辅助系统的底层数据库架构设计。系统采用 **SQLAlchemy 2.0** ORM 进行管理，支持从 SQLite (MVP) 到 PostgreSQL (生产环境) 的无缝迁移，并原生支持 SaaS 多租户架构。

---

## 1. 核心设计原则

1. **SaaS 多租户隔离**：在物理表级别，所有实体表（除极少数全局字典表外）强制继承 `TenantBase`，并带有 `tenant_id` 字段。所有涉及数据的读写，必须过滤 `tenant_id`。
2. **读写分离的数据分类**：
   - **基础业务数据**：如公司资质库、市场参考价。这类数据属于企业级基础资产，更新频率低，但作为 AI 判定的重要 Context，读取频率极高。
   - **AI 过程数据**：由 AI 引擎针对单次标书项目生成的结果，写入频率高，且需要和原始文档保持强溯源关联。
3. **AI 可解释性溯源**：AI 生成的每一条判定结果（匹配度、风险点等），必须强制落库 `ai_reasoning`（AI 判定理由），支持前端点击溯源。
4. **AI-Native 预留**：针对 RAG 需求，分块表预留了向量存储能力（未来对接 pgvector）。

---

## 2. 实体关系图 (ER Diagram)

以下是由系统架构导出的底层 ER 图：

```mermaid
erDiagram
    PROJECT ||--o{ DOCUMENT : "拥有的文档"
    PROJECT ||--o{ QUALIFICATION_MATCH : "生成的资质匹配结果"
    PROJECT ||--o{ RISK_ITEM : "扫描出的风险项"
    PROJECT ||--o{ COST_ESTIMATE : "相关的成本测算"

    DOCUMENT ||--o{ DOC_CHUNK : "解析分块(RAG)"

    COMPANY_QUALIFICATION |o--o{ QUALIFICATION_MATCH : "引用"
    MARKET_PRICE_REF |o--o{ COST_ESTIMATE : "引用"

    %% ----------------核心基础表----------------
    TENANT_BASE {
        string id PK "UUID"
        string tenant_id FK "租户ID(多租户隔离核心)"
        datetime created_at
        datetime updated_at
    }

    COMPANY_QUALIFICATION {
        string name "资质名称(如: ISO9001)"
        string level "资质等级"
        date expiry_date "过期时间"
        string file_url "资质文件URL"
    }

    MARKET_PRICE_REF {
        string item_name "物品/服务名称"
        string category "分类"
        float unit_price "单价"
        string unit "单位"
    }

    %% ----------------项目执行表----------------
    PROJECT {
        string name "项目/标书名称"
        string status "状态"
    }

    DOCUMENT {
        string project_id FK
        string filename "文件名"
        string file_path "物理存储路径"
        string parse_status "解析状态(pending/parsed)"
    }

    DOC_CHUNK {
        string document_id FK
        text content "分块文本片段"
        int page_num "原文档页码(用于UI溯源)"
        vector embedding "预留: 向量检索字段"
    }

    %% ----------------AI 分析结果表----------------
    QUALIFICATION_MATCH {
        string project_id FK
        string qualification_id FK "匹配到的我方资质"
        text requirement_text "标书要求原文"
        string match_level "匹配度(GREEN/YELLOW/RED)"
        text ai_reasoning "AI详细判定依据"
    }

    RISK_ITEM {
        string project_id FK
        string risk_type "风险类型(商务/法律/技术)"
        text risk_text "风险条款原文"
        string severity "严重程度"
        text ai_reasoning "AI分析意见"
    }

    COST_ESTIMATE {
        string project_id FK
        string reference_price_id FK "引用的参考价格字典"
        string item_name "标书采购项"
        int quantity "数量"
        float calculated_total "总价"
    }
```

*(注：上述所有表均在代码层面继承自 `TenantBase`，底层默认包含 `id`, `tenant_id`, `created_at`, `updated_at` 四个基石字段。)*

---

## 3. ORM 代码结构说明

后端 ORM 模型位于 `backend/app/models/`，按业务领域拆分：

- `base.py`：定义声明式基类与 `TenantBase` 多租户基类。
- `business.py`：定义静态的基础业务数据（公司资质、参考价）。
- `project.py`：定义项目主线逻辑（项目本体、上传的文档、以及切分后的 RAG 数据块）。
- `ai_analysis.py`：定义高度动态的 AI 报告数据（风险扫描结果、资质红绿灯匹配度、成本核算单）。

## 4. 迁移与部署建议 (Migrations)

1. **初期快速开发 (MVP)**
   采用默认配置，连接字符串使用 SQLite (`sqlite:///./app.db`)。使用 Alembic 或 SQLAlchemy 原生方法在内存或本地文件中构建表，进行 CRUD 和接口联调。
2. **生产环境 (Production)**
   - 切换环境变量连接至 PostgreSQL (`postgresql://user:pass@host/dbname`)。
   - 使用 Alembic 初始化并生成第一版 Migration Script (`alembic revision --autogenerate -m "init"`)。
   - 配置高可用（HA）时无需更改上述业务模型，仅配置驱动程序。
   - 数据安全加密依靠云厂商底层 TDE（Transparent Data Encryption）即可，对应用层透明。
