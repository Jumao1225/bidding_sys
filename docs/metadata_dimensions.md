# 五个维度元数据字段参考文档

> 创建时间：2026-07-15
> 维护路径：`backend/app/services/metadata/`

本文档记录系统中用于从招标文件中自动提取结构化信息的五个核心元数据维度，每个维度对应一个独立的 Pydantic Schema 和 Service 类。所有维度均继承自 `BaseMetadataService`，通过大模型（LLM）结构化输出能力进行信息抽取，并自动落盘至 PostgreSQL。

> **注意**：每个维度均包含一个 `reasoning` 字段，用于大模型 CoT 链式思考输出，该字段在 `BaseMetadataService._save_to_db` 中会被自动过滤，**不会写入数据库**。

---

## 1. 📅 时间轴维度 — `TimelineSchema`

- **服务文件**：`app/services/metadata/timeline_service.py`
- **数据库模型**：`TimelineMetadata`
- **专家角色**：招投标项目经理与全局调度主管
- **用途**：提取项目核心身份标识与时间轴约束，供 Supervisor Agent 初始化项目倒排看板

| 字段名 | 类型 | 说明 |
|---|---|---|
| `project_id_code` | `Optional[str]` | 项目编号/招标编号/标段编号 |
| `project_name` | `Optional[str]` | 项目名称 |
| `bid_deadline` | `Optional[str]` | 开标/投标文件递交截止时间（格式：`YYYY-MM-DD HH:MM`） |
| `qa_deadline` | `Optional[str]` | 答疑/澄清截止时间（格式：`YYYY-MM-DD HH:MM`） |
| `construction_period_days` | `Optional[int]` | 工期天数（纯整数，月份自动换算为天） |
| `document_copies` | `Optional[str]` | 标书份数要求（如"正本1份，副本4份"） |
| `reasoning` | `Optional[str]` | CoT 推导过程（**不落库**） |

---

## 2. 💰 财务维度 — `FinancialSchema`

- **服务文件**：`app/services/metadata/financial_service.py`
- **数据库模型**：`FinancialMetadata`
- **专家角色**：注册造价师与投融资财务专家
- **用途**：提炼财务与资金流核心约束，作为 Cost Agent 报价引擎的硬性数学上限

| 字段名 | 类型 | 说明 |
|---|---|---|
| `max_price_limit` | `Optional[str]` | 最高投标限价（控制价），含币种 |
| `budget` | `Optional[str]` | 项目预算/投资估算额 |
| `bid_bond_ratio` | `Optional[str]` | 投标保证金金额或比例 |
| `performance_bond_ratio` | `Optional[str]` | 履约保证金金额或比例 |
| `payment_milestones` | `Optional[list[PaymentMilestone]]` | 付款节点数组，每项含 `stage`（阶段）/ `percentage`（比例）/ `condition`（触发条件） |
| `reasoning` | `Optional[str]` | CoT 推导过程（**不落库**） |

### `PaymentMilestone` 子结构

| 字段名 | 类型 | 说明 |
|---|---|---|
| `stage` | `str` | 付款阶段名称（如"预付款"、"进度款"、"验收款"、"质保金"） |
| `percentage` | `str` | 付款比例（如"30%"） |
| `condition` | `str` | 付款触发条件（如"合同签订后7个工作日内"） |

---

## 3. 📜 资质维度 — `QualificationSchema`

- **服务文件**：`app/services/metadata/qualification_service.py`
- **数据库模型**：`QualificationMetadata`
- **专家角色**：招投标法务合规官与资质审核专家
- **用途**：提炼资格合规与资质门槛，供商务 Agent 向公司资质库和业绩库匹配原件

| 字段名 | 类型 | 说明 |
|---|---|---|
| `industry_qualifications` | `Optional[list[str]]` | 行业资质门槛（如建筑业/电力工程资质等级，完整名称+等级） |
| `special_licenses` | `Optional[list[str]]` | 特种许可证（安全生产许可证、特种设备制造许可证、ISO认证等） |
| `core_personnel_certs` | `Optional[Dict[str, Any]]` | 核心人员证书要求（格式：`{岗位名称: 证书名称及等级要求}`） |
| `historical_performance_reqs` | `Optional[str]` | 历史业绩门槛（时间段+规模参数的精炼纯文本） |
| `reasoning` | `Optional[str]` | CoT 推导过程（**不落库**） |

---

## 4. ⚙️ 工程维度 — `EngineeringSchema`

- **服务文件**：`app/services/metadata/engineering_service.py`
- **数据库模型**：`EngineeringMetadata`
- **专家角色**：项目总工与现场施工技术专家
- **用途**：提取核心设备指标与非标施工难点，供 Tech Worker 检索专项施工工艺知识库

| 字段名 | 类型 | 说明 |
|---|---|---|
| `main_equipment_quantities` | `Optional[Dict[str, str]]` | 主要标的物定量配置（格式：`{设备名称: 规格及数量}`，如 `{光伏组件: 545Wp，1000块}`） |
| `special_working_conditions` | `Optional[list[str]]` | 特殊/高难度施工工况短语数组（如 `["换瓦", "大跨度跨河布线", "夜间施工"]`） |
| `reasoning` | `Optional[str]` | CoT 推导过程（**不落库**） |

---

## 5. 🏆 评标维度 — `EvaluationSchema`

- **服务文件**：`app/services/metadata/evaluation_service.py`
- **数据库模型**：`EvaluationMetadata`
- **专家角色**：资深评标专家与售后运维总监
- **用途**：提取评分权重分布与售后罚则约束，供 Service Worker 生成《服务承诺函》

| 字段名 | 类型 | 说明 |
|---|---|---|
| `price_weight` | `Optional[int]` | 价格（商务）权重分值（纯整数，如 `30`） |
| `tech_weight` | `Optional[int]` | 技术权重分值（纯整数，如 `50`） |
| `warranty_years` | `Optional[str]` | 质保期/缺陷责任期年限（如"2年"） |
| `after_sales_response_hours` | `Optional[int]` | 售后响应时限（纯小时数，如 `4`） |
| `penalty_clauses` | `Optional[list[str]]` | 违约/工期延误/性能扣罚条款字符串数组 |
| `reasoning` | `Optional[str]` | CoT 推导过程（**不落库**） |

---

## 架构概览

```
BaseMetadataService (base.py)
├── TimelineService      → TimelineSchema      → TimelineMetadata（DB）
├── FinancialService     → FinancialSchema     → FinancialMetadata（DB）
├── QualificationService → QualificationSchema → QualificationMetadata（DB）
├── EngineeringService   → EngineeringSchema   → EngineeringMetadata（DB）
└── EvaluationService    → EvaluationSchema    → EvaluationMetadata（DB）
```

所有维度的提取流程统一为：
1. 接收文档分块上下文 `context` 与 `document_id`
2. 注入专家角色 `system_prompt` + 任务约束（宁缺毋滥、明确豁免、CoT）
3. 调用 `llm_service.generate_structured_output()` 获取 Pydantic 对象
4. 过滤 `reasoning` 等非数据库字段后，自动 upsert 至对应的 PostgreSQL 表
