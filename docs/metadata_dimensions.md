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

| 核心字段名 | 类型 | 说明 |
|---|---|---|
| `project_id_code` | `Optional[str]` | 项目编号/招标编号/标段编号 |
| `project_name` | `Optional[str]` | 项目名称 |
| `tender_segment` | `Optional[str]` | 标段/包件名称 |
| `acquisition_info` | `Optional[TenderAcquisitionInfo]` | 招标文件获取/领购渠道及售价 |
| `contacts` | `list[ContactPerson]` | 招投标通讯录（甲方、代理、答疑联系人等） |
| `bid_deadline` | `Optional[str]` | 投标/开标截止时间（`YYYY-MM-DD HH:MM`） |
| `bid_validity_days` | `Optional[int]` | 投标有效期（天数） |
| `tender_milestones` | `list[TenderMilestone]` | 筹备期全流程倒排节点（踏勘、提问、保证金等） |
| `document_requirements` | `Optional[DocumentRequirement]` | 标书份数、装订及密封要求 |
| `construction_period_days` | `Optional[int]` | 总工期天数（纯整数） |
| `construction_period_description` | `Optional[str]` | 工期要求描述原文 |
| `reasoning` | `Optional[str]` | CoT 推导过程（**不落库**） |

### 子结构说明
- **`TenderAcquisitionInfo`**: `acquisition_method`, `doc_fee`, `download_url_or_address`, `acquisition_deadline`, `required_materials`。
- **`ContactPerson`**: `role_type`, `unit_name`, `contact_name`, `phone`, `email`, `address`。
- **`TenderMilestone`**: `name`, `deadline`, `is_mandatory` (是否废标项), `description`。
- **`DocumentRequirement`**: `submission_type` (电子标/纸质标), `original_copies`, `duplicate_copies`, `electronic_copies`, `seal_requirements`, `online_upload_platform`。

---

## 2. 💰 财务维度 — `FinancialSchema`

- **服务文件**：`app/services/metadata/financial_service.py`
- **数据库模型**：`FinancialMetadata`
- **专家角色**：注册造价师与投融资财务专家
- **用途**：提炼财务与资金流核心约束，作为 Cost Agent 报价引擎的硬性数学上限

| 核心字段名 | 类型 | 说明 |
|---|---|---|
| `budget` | `Optional[MoneyAmount]` | 项目总采购预算/资金来源总额 |
| `max_price_limit` | `Optional[MoneyAmount]` | 最高投标限价/招标控制价（总价上限，超限即废标） |
| `sub_package_budgets` | `list[SubPackageBudget]` | 多标包/分包项目的各包预算明细 |
| `unit_price_limits` | `dict[str, float]` | 关键品目/人月/单价控制价限制字典 |
| `provisional_sum` | `Optional[MoneyAmount]` | 暂列金额/不可预见费（不可竞争费用） |
| `contract_price_type` | `Optional[str]` | 合同计价方式（如：固定总价、固定单价） |
| `tax_rate_requirement` | `Optional[str]` | 税率要求 |
| `bid_bond` | `Optional[BondInfo]` | 投标保证金详情 |
| `performance_bond` | `Optional[BondInfo]` | 履约保证金详情 |
| `warranty_bond` | `Optional[BondInfo]` | 质量保证金/缺陷责任金详情 |
| `advance_payment_ratio` | `Optional[float]` | 预付款比例 |
| `payment_milestones` | `list[PaymentMilestone]` | 付款阶段明细 |
| `price_adjustment_clause` | `Optional[str]` | 调价机制/原材料上涨补偿条款说明 |
| `delayed_payment_penalty` | `Optional[str]` | 甲方迟延付款的利息/违约金补偿条款 |
| `reasoning` | `Optional[str]` | CoT 推导过程（**不落库**） |

### `MoneyAmount` 子结构
包含字段：`amount` (float), `currency` (str), `amount_in_words` (str)。

### `SubPackageBudget` 子结构
包含字段：`package_name` (str), `budget` (MoneyAmount)。

### `BondInfo` 子结构
包含字段：`amount_description` (str), `calculated_amount` (float), `acceptable_forms` (list[str]), `refund_condition` (str)。

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

| 核心字段名 | 类型 | 说明 |
|---|---|---|
| `min_registered_capital_wuyuan` | `Optional[float]` | 最低注册资本要求（万元） |
| `credit_and_legal_reqs` | `list[str]` | 信用与合规要求（如无重大违法记录、失信被执行人等） |
| `mandatory_qualifications` | `list[str]` | 强制性企业资质门槛（不满足即废标） |
| `system_certifications` | `list[str]` | 体系认证/特种许可（如 ISO、安全生产许可证等） |
| `personnel_requirements` | `list[PersonnelRequirement]` | 核心人员及证书匹配要求明细，见下表 |
| `performance_requirements` | `list[PerformanceRequirement]` | 历史同类业绩门槛，已结构化供 Agent 检索，见下表 |
| `bonus_qualifications` | `list[str]` | 资质/业绩/人员方面的评分加分项（非废标项） |
| `reasoning` | `Optional[str]` | CoT 推导过程（**不落库**） |

### `PersonnelRequirement` 子结构
包含字段：`role`, `cert_name`, `count`, `is_mandatory`, `other_requirements`。

### `PerformanceRequirement` 子结构
包含字段：`time_frame_years`, `min_amount_wuyuan`, `required_count`, `keyword_or_domain`, `description`。

---

## 4. ⚙️ 工程维度 — `EngineeringSchema`

- **服务文件**：`app/services/metadata/engineering_service.py`
- **数据库模型**：`EngineeringMetadata`
- **专家角色**：项目总工与现场施工技术专家
- **用途**：提取核心设备指标与非标施工难点，供 Tech Worker 检索专项施工工艺知识库

| 核心字段名 | 类型 | 说明 |
|---|---|---|
| `main_equipment_list` | `list[EquipmentItem]` | 主要设备、材料或软件标的物配置清单明细 |
| `special_working_conditions` | `list[str]` | 特殊/高难度施工/实施工况（如：`["换瓦", "夜间施工"]`） |
| `site_environment_constraints` | `Optional[str]` | 现场环境与施工限制说明 |
| `mandatory_standards` | `list[str]` | 强制性国家/行业/技术标准（如 GB、ISO 规范） |
| `tech_validation` | `Optional[TechValidationRequirement]` | 样品送样、现场 POC 答辩演示及第三方检测报告要求 |
| `safety_and_env_requirements` | `list[str]` | 安全生产、文明施工及环保特别约束 |
| `reasoning` | `Optional[str]` | CoT 推导过程（**不落库**） |

### 子结构说明
- **`EquipmentItem`**: `item_name`, `specifications`, `quantity`, `unit`, `brand_requirements`, `key_parameters` (核心带 * 号星号参数列表)。
- **`TechValidationRequirement`**: `sample_required`, `sample_description`, `poc_demo_required`, `test_report_requirements`。

---

## 5. 🏆 评标维度 — `EvaluationSchema`

- **服务文件**：`app/services/metadata/evaluation_service.py`
- **数据库模型**：`EvaluationMetadata`
- **专家角色**：资深评标专家与售后运维总监
- **用途**：提取评分权重分布与售后罚则约束，供 Service Worker 生成《服务承诺函》

### 动态解耦架构
为了适配各类千变万化的评分标准，采取“核心强 Schema + 动态扩展 JSON”的混合架构：

| 核心固定字段名 | 类型 | 说明 |
|---|---|---|
| `evaluation_method` | `str` | 评标方法（如：综合评分法、最低投标价法） |
| `total_score` | `float` | 评标总分，通常为 100.0 |
| `weight_distribution` | `dict[str, float]` | 各大类权重汇总字典（如 `{"商务分": 30, "技术分": 50}`） |
| `score_tree` | `list[ScoreDetail]` | 动态提取出的所有评分细则明细列表（树状或平铺），见下表 |
| `hard_service_requirements` | `dict[str, Any]` | 专门剥离给 Service Worker 用的售后/硬性约束（如质保、罚金） |
| `reasoning` | `Optional[str]` | CoT 推导过程（**不落库**） |

#### `ScoreDetail` 评分细则实体
包含字段：`item_code`, `category`, `sub_category`, `title`, `max_score`, `scoring_criteria`, `scoring_type`, `rules_summary`。

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

---

## 🚀 后续优化规划 (Future Roadmap)

1. **RAG 检索章节路由 (Chapter Routing Agent)**
   - **背景**：目前的 RAG 检索在底层（`rag_service.search_bidding_document`）已经原生支持通过 `section_title` 进行强制章节过滤（例如限定仅在“评标办法”章节中检索）。
   - **规划**：未来考虑在调用各个维度的 Metadata Service 之前，设计一个专门的 **“路由识别 Agent” (Routing Agent)**。
   - **职责**：该 Agent 负责在提取前分析文档的大纲（Table of Contents），动态决定当前提取维度（如评标、财务、工程）应该限定在哪些特定的 `section_title` 中，并自动填充检索工具的 `section_title` 字段，从而实现全自动的、极高精度的上下文截取，进一步降低 RAG 的信噪比与误召回率。
