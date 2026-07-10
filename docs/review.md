
# 客观评判一下这个招标投标系统的架构设计合理性，如果可以优化提出可靠的优化方案；

## 总体结论

这套架构作为**招投标系统 MVP**是合理的，技术栈也没有明显错误；但如果目标是形成可长期使用、可审计、可多人协作、能够稳定生成正式投标文件的企业系统，目前设计仍然偏“AI Agent Demo 架构”。

综合判断：

| 维度             |               评价 |
| ---------------- | -----------------: |
| 技术栈合理性     |               8/10 |
| 模块分层         |               7/10 |
| 异步任务设计     |               7/10 |
| AI工作流设计     |               6/10 |
| 招投标业务完整性 |               5/10 |
| 数据可追溯性     |               5/10 |
| 生产稳定性       |               5/10 |
| 安全与审计       |               4/10 |
| 综合             | **约6.2/10** |

当前方案的优点是 FastAPI、Celery、LangGraph、PostgreSQL、MinIO 的组合能够支撑长文档解析、异步分析和文件生成；前后端也做了较清楚的目录划分。主要问题不是技术选型，而是：

> **把过多确定性业务做成了 Agent，同时缺少招投标系统真正核心的结构化数据模型、证据链、人工审核、版本管理和一致性校验。**

现有架构定义了 Extractor、Compliance、Strategy、Cost、Writer 等多个 Agent，并通过 LangGraph 编排，基本方向可以保留，但需要重新划分 Agent 与传统程序的职责。

---

# 一、当前架构合理的地方

## 1. 基础技术栈能够支撑这个系统

### FastAPI

适合作为：

* 文件上传接口；
* 项目、材料、响应项管理接口；
* SSE任务进度接口；
* 标书预览与导出接口；
* 企业资料库查询接口。

### Celery

招标文件解析、OCR、向量化、章节生成、DOCX渲染都可能耗时几十秒到数分钟，不能占用HTTP请求线程。使用Celery作为外部异步任务队列是合理的。

### LangGraph

适合处理存在条件分支、重试、人工确认和上下文传递的AI工作流，例如：

```text
文件解析
→ 要求提取
→ 合规检查
→ 人工确认
→ 评分策略
→ 章节生成
→ 一致性检查
→ 人工封版
```

### PostgreSQL、pgvector和MinIO

组合基本合理：

* PostgreSQL保存业务数据；
* pgvector保存语义检索向量；
* MinIO保存原始招标文件、投标附件和生成的DOCX/PDF；
* Redis承担Celery消息和实时进度事件。

不需要为了“AI系统”一开始就引入过多数据库。

---

## 2. Agent不直接操作HTTP连接是正确的

架构要求Agent不能直接操作SSE，而是输出状态事件，由外围层统一推送。这是正确的边界。

否则Agent会与Web请求生命周期耦合，出现：

* 前端断开导致任务失败；
* 无法从断点继续；
* 测试困难；
* 无法复用到批处理任务；
* Agent业务代码包含大量网络连接代码。

---

## 3. 前端按业务功能划分比按页面划分更合理

`features/document`、`features/risk`、`features/strategy`、`features/writer` 的功能域组织方式是合理的，比把所有代码放在 `pages` 和 `components` 中更容易维护。

---

## 4. 把测试独立出来是正确的

单元测试、集成测试、接口测试、Fixtures分开是合理的。不过目前只解决了“测试代码放在哪里”，还没有解决“AI系统应该测什么”。

---

# 二、当前架构最主要的问题

## 1. 多智能体使用过度

当前设计将以下模块全部定义为Agent：

* Extractor Agent；
* Compliance Agent；
* Strategy Agent；
* Cost Agent；
* Writer Agent。

这里至少有一半不应该是自主Agent。

### 应该由确定性程序实现的部分

| 功能               | 推荐实现        |
| ------------------ | --------------- |
| 文件格式识别       | 普通代码        |
| PDF/DOCX解析       | 文档解析流水线  |
| 表格抽取           | 解析器+规则     |
| 报价加总           | 确定性计算器    |
| 税率计算           | 规则引擎        |
| 页码、目录生成     | DOCX渲染器      |
| 投标文件完整性检查 | 规则引擎        |
| 证书有效期检查     | 日期规则        |
| 金额一致性检查     | 确定性校验      |
| 品牌型号一致性检查 | 数据库约束+规则 |
| 必填材料检查       | 清单规则        |

### 适合使用大模型的部分

| 功能             | 大模型职责           |
| ---------------- | -------------------- |
| 招标条款语义理解 | 辅助提取与分类       |
| 隐含风险识别     | 提出候选风险         |
| 评分策略分析     | 提出得分建议         |
| 技术方案初稿     | 基于真实资料生成文本 |
| 商务响应初稿     | 基于规则和证据生成   |
| 前后矛盾解释     | 语义级一致性分析     |
| 问答助手         | 基于项目材料回答问题 |

尤其是 `Cost Agent` 风险较高。报价和成本属于高风险确定性业务，不能让模型自主生成数量、单价和总价。

### 推荐原则

```text
AI负责理解、归纳、草拟和发现问题
程序负责计算、校验、存储、授权和最终生成
人工负责报价、承诺、资质真实性和最终封版
```

---

## 2. “Supervisor统一调度”不适合核心投标流程

Supervisor适合处理用户自由提问，例如：

* “这个付款条件有什么风险？”
* “哪些条款可能导致废标？”
* “帮我解释评分办法。”

但不适合控制正式标书生成主链路。

核心投标流程是相对固定的：

```text
上传文件
→ 解析
→ 提取要求
→ 形成响应矩阵
→ 匹配企业证据
→ 编写方案
→ 填写报价
→ 一致性校验
→ 人工审核
→ 导出
```

如果让Supervisor自行决定下一步，会出现：

* 同一份文件多次运行路径不同；
* 缺少关键步骤；
* 处理结果不可复现；
* 难以验收；
* 发生错误时难以定位；
* 无法证明投标文件是如何生成的。

### 最优方案

采用真正的“混合路由”：

```text
正式工作流：固定DAG或状态机
自由问答：Supervisor Agent
专业分析：受控LLM节点
外部工具：Skill Registry
```

核心流程必须是确定性工作流，Supervisor不得绕过正式审批节点。

---

## 3. 全局 `BiddingState` 容易膨胀

文档中要求所有Agent依赖统一的 `BiddingState`。思路本身正确，但如果将以下内容全部放进去：

* 招标全文；
* 所有文本块；
* 评分表；
* 风险项；
* 报价明细；
* 标书章节；
* 附件内容；
* 聊天历史；

状态会迅速变得巨大，并导致：

* LangGraph状态序列化缓慢；
* Redis或数据库存储成本高；
* 并行节点容易覆盖彼此数据；
* 重试时重复传输大量内容；
* 无法清晰追踪数据版本。

### 优化后的状态设计

`BiddingState` 只保存引用和控制信息：

```python
class BiddingState(TypedDict):
    project_id: str
    workflow_run_id: str
    source_document_version_id: str
    requirement_set_version: int
    current_stage: str
    completed_nodes: list[str]
    failed_nodes: list[str]
    review_status: str
    artifact_version_id: str | None
```

实际业务数据放入数据库：

```text
Requirement
ScoringItem
RiskItem
Evidence
ResponseItem
CostItem
ProposalSection
ReviewDecision
```

这样LangGraph负责流程，PostgreSQL负责事实。

---

## 4. 目录结构只有技术分层，缺少业务域边界

当前后端目录是：

```text
api
core
db
schemas
services
agents
skills
graph
worker
```

这种结构前期直观，但随着项目扩大，容易出现：

* `services/` 堆积几十个文件；
* 所有ORM都放在 `db/models`；
* 一个业务改动跨越五六个目录；
* 项目、文档、报价、企业资产相互耦合；
* 无法明确谁负责业务规则。

这并不是真正的DDD，更接近传统分层架构。

### 推荐改为“业务域优先”

```text
backend/app/
├── modules/
│   ├── projects/
│   │   ├── api.py
│   │   ├── schemas.py
│   │   ├── models.py
│   │   ├── repository.py
│   │   └── service.py
│   ├── documents/
│   │   ├── parsers/
│   │   ├── chunking/
│   │   ├── api.py
│   │   ├── models.py
│   │   └── service.py
│   ├── requirements/
│   ├── compliance/
│   ├── scoring/
│   ├── enterprise_assets/
│   ├── pricing/
│   ├── proposal/
│   ├── review/
│   └── export/
├── workflows/
│   ├── tender_analysis/
│   ├── proposal_generation/
│   └── final_validation/
├── ai/
│   ├── model_gateway.py
│   ├── prompt_registry.py
│   ├── structured_output.py
│   ├── evaluators/
│   └── tools/
├── infrastructure/
│   ├── database/
│   ├── object_storage/
│   ├── queue/
│   ├── event_bus/
│   └── observability/
├── core/
└── main.py
```

这种结构更适合招投标系统，因为一个完整功能的模型、服务、接口和规则都在同一业务域下。

---

## 5. 文档解析被错误地简化成一个OCR Skill

`ocr_skill.py` 无法承担完整招标文件处理。

真实招标文件可能包括：

* 原生PDF；
* 扫描PDF；
* DOCX；
* Excel报价清单；
* PDF中的复杂表格；
* 页眉页脚；
* 加粗、斜体、下划线等实质性标记；
* 图片中的平面图；
* 招标补充文件；
* 多版本澄清文件。

尤其是招标文件中“斜体且带下划线内容为实质性要求”这类规则，单纯提取文本会丢失格式语义。

### 应建立独立文档处理域

```text
Document Intake
├── 文件安全检查
├── 文件类型识别
├── 原始文件存档
├── PDF/DOCX/Excel解析
├── OCR回退
├── 版面结构识别
├── 目录与章节识别
├── 表格抽取
├── 格式标记提取
├── 页码坐标保留
└── 标准化DocumentBlock
```

标准块至少需要：

```python
class DocumentBlock:
    block_id: str
    document_version_id: str
    page_no: int
    section_path: list[str]
    block_type: str
    text: str
    bbox: list[float] | None
    table_data: dict | None
    is_bold: bool
    is_italic: bool
    is_underlined: bool
    source_hash: str
```

后续每一项风险、评分要求、技术参数都必须能回溯到：

```text
原文件 → 页码 → 章节 → 原始文本块
```

---

## 6. 缺少招投标系统最核心的“响应矩阵”

当前架构关注：

* 风险；
* 策略；
* 成本；
* 写作。

但真正贯穿整个系统的核心对象应该是：

## 招标要求响应矩阵

```text
招标要求
→ 要求类型
→ 是否实质性
→ 是否满足
→ 响应内容
→ 支撑证据
→ 负责人
→ 审核状态
→ 投标文件位置
```

建议数据结构：

```python
class Requirement:
    id: str
    project_id: str
    requirement_code: str
    category: str
    source_document_id: str
    source_page: int
    source_text: str
    mandatory_level: str
    response_status: str
    response_text: str | None
    evidence_ids: list[str]
    owner_id: str | None
    reviewer_id: str | None
    review_status: str
    proposal_section_id: str | None
```

没有这个核心模型，后面的合规检查、得分策略和投标文件生成都会成为相互独立的AI输出，无法形成闭环。

---

## 7. 缺少企业投标资产库

架构只在Skill示例中提到未来查询ERP，但企业投标系统最重要的长期资产不是Agent，而是：

* 企业营业执照；
* 资质证书；
* 许可证；
* 财务报告；
* 纳税和社保证明；
* 人员证书；
* 人员简历；
* 类似项目业绩；
* 产品参数；
* 厂商授权；
* 检测报告；
* 认证证书；
* 售后服务承诺；
* 标准方案模板；
* 历史中标文件。

这应该成为一级业务模块：

```text
enterprise_assets/
├── company_profiles
├── qualifications
├── certificates
├── employees
├── employee_credentials
├── project_cases
├── products
├── product_certifications
├── manufacturers
├── templates
└── evidence_packages
```

系统生成投标文件时，不是让模型自由编写企业能力，而是从资产库中匹配真实证据。

---

## 8. Writer Agent不应直接生成Word文件

“Writer Agent生成Word”将内容生成和格式渲染混在一起，会造成：

* 同一内容多次生成格式不一致；
* 页码和目录不稳定；
* 表格容易错位；
* 盖章页、签字页难控制；
* 无法局部更新；
* 无法对比版本；
* 难以精确定位引用来源。

### 正确链路

```text
Writer LLM
→ 输出结构化ProposalSection JSON
→ 人工编辑和审核
→ 模板渲染服务
→ DOCX
→ PDF预览
```

例如：

```json
{
  "section_code": "8.3",
  "title": "施工进度计划",
  "content_blocks": [
    {
      "type": "paragraph",
      "text": "本项目计划在收到进场通知后60日内完成……"
    },
    {
      "type": "table",
      "data_source": "schedule_plan_v3"
    }
  ],
  "requirement_ids": ["REQ-0012", "REQ-0015"],
  "evidence_ids": ["EVD-101"]
}
```

再由确定性的DOCX渲染器负责：

* 标题样式；
* 目录；
* 页眉页脚；
* 表格；
* 图片；
* 页码；
* 正副本标记；
* 附件插入。

---

## 9. Redis Pub/Sub不适合可靠进度传输

现有链路是：

```text
Agent → Redis Pub/Sub → FastAPI → SSE → 前端
```

问题是Redis Pub/Sub不持久化消息。

如果出现：

* 前端刷新；
* SSE断线；
* FastAPI重启；
* 网络短暂中断；

用户可能永久丢失进度事件。

### 推荐方案

使用以下任一种：

1. Redis Streams；
2. PostgreSQL `job_events` 表；
3. Redis Streams + 数据库最终状态。

事件结构：

```json
{
  "event_id": 158,
  "task_id": "task-xxx",
  "stage": "compliance_analysis",
  "status": "running",
  "progress": 45,
  "message": "已识别12项实质性要求",
  "created_at": "..."
}
```

前端断线后通过 `Last-Event-ID` 继续拉取，不会丢失事件。

---

## 10. 重试机制设计过于简单

“所有LLM请求使用tenacity重试”不够可靠，甚至可能放大问题。

不同错误应区别处理：

| 错误         | 处理方式            |
| ------------ | ------------------- |
| 网络超时     | 指数退避重试        |
| 429限流      | 根据Retry-After重试 |
| 5xx          | 有限次数重试        |
| 参数错误     | 不重试              |
| 上下文超限   | 自动拆分或压缩      |
| JSON格式错误 | 结构修复后重试      |
| 内容安全拒绝 | 转人工处理          |
| 余额不足     | 立即失败并告警      |
| 重复任务     | 幂等返回已有结果    |

还应增加：

* 单节点超时；
* 总任务超时；
* 幂等键；
* 死信队列；
* 熔断；
* 限流；
* 最大成本预算；
* 人工恢复入口。

---

## 11. API统一返回HTTP 200不合理

架构要求统一为：

```json
{
  "code": 200,
  "message": "success",
  "data": {}
}
```

统一响应结构可以保留，但不能所有请求都返回HTTP 200。

应使用正确状态码：

* `200`：查询成功；
* `201`：创建成功；
* `202`：异步任务已接受；
* `400`：参数或业务请求错误；
* `401`：未登录；
* `403`：无权限；
* `404`：资源不存在；
* `409`：状态冲突；
* `422`：校验失败；
* `500`：服务异常。

例如上传招标文件并创建异步任务，最合适的是HTTP `202 Accepted`。

---

## 12. Skill机制不是真正的“热插拔”

目前所谓热插拔，是在Agent代码中手动导入：

```python
from app.skills.erp_skill import query_erp_inventory
available_skills = [query_erp_inventory]
```

这仍然需要：

* 修改代码；
* 重启服务；
* 重新部署。

严格来说不属于热插拔。

### 应建立Skill Registry

每个Skill包含：

```text
技能ID
版本
输入Schema
输出Schema
允许使用的Agent
读取/写入权限
超时
重试策略
风险级别
是否需要人工确认
启用状态
```

调用链：

```text
Agent
→ Skill Registry
→ 权限策略检查
→ 参数校验
→ Tool Adapter
→ 审计记录
→ 返回结果
```

涉及以下行为必须人工确认：

* 发送邮件；
* 修改ERP数据；
* 提交报价；
* 删除文件；
* 向外部平台提交标书；
* 发起付款或盖章流程。

---

# 三、建议的目标架构

## 1. 总体分层

```text
┌───────────────────────────────────────────────┐
│                 React投标工作台                │
│ 项目中心｜要求矩阵｜评分矩阵｜报价｜编写｜审核 │
└──────────────────────┬────────────────────────┘
                       │ REST / SSE
┌──────────────────────▼────────────────────────┐
│                  FastAPI接入层                 │
│ 鉴权｜权限｜API｜任务查询｜事件订阅｜文件下载   │
└─────────────┬───────────────────┬─────────────┘
              │                   │
       同步业务服务          异步任务提交
              │                   │
┌─────────────▼──────────┐  ┌─────▼─────────────┐
│    领域应用服务层       │  │ Celery任务执行层   │
│ 项目/资产/报价/审核     │  │ 解析/分析/生成/导出│
└─────────────┬──────────┘  └─────┬─────────────┘
              │                   │
              └─────────┬─────────┘
                        │
┌───────────────────────▼───────────────────────┐
│              确定性工作流与LangGraph           │
│ 文档解析 → 要求提取 → 风险/评分 → 编写 → 校验  │
│                  人工审核节点                  │
└───────────────┬───────────────────────────────┘
                │
┌───────────────▼───────────────────────────────┐
│                   AI能力层                    │
│ Model Gateway｜Prompt Registry｜LLM Nodes      │
│ Retrieval｜Structured Output｜Evaluation       │
└───────────────┬───────────────────────────────┘
                │
┌───────────────▼───────────────────────────────┐
│                基础设施与数据层                │
│ PostgreSQL｜pgvector｜MinIO｜Redis Streams      │
│ 日志｜指标｜链路追踪｜密钥管理｜审计日志        │
└───────────────────────────────────────────────┘
```

---

## 2. 推荐工作流

```text
创建投标项目
    ↓
上传招标文件及补充文件
    ↓
文件安全扫描、存档、版本化
    ↓
版面解析、OCR、表格和格式提取
    ↓
生成章节树和DocumentBlock
    ↓
提取项目基本信息
    ↓
提取资格条件、实质性条款、技术参数、商务条款
    ↓
提取评分办法和报价要求
    ↓
生成招标要求响应矩阵
    ↓
规则引擎执行第一轮废标检查
    ↓
LLM执行语义风险补充分析
    ↓
人工确认要求矩阵
    ↓
匹配企业资质、业绩、人员、产品和案例
    ↓
形成缺失材料清单
    ↓
制定投标策略和预计得分
    ↓
人工录入并审核成本报价
    ↓
按章节生成投标文件初稿
    ↓
逐项绑定要求、证据和章节
    ↓
资格、商务、技术、报价一致性检查
    ↓
多人审核和问题整改
    ↓
DOCX模板渲染
    ↓
PDF预览和最终封版
```

---

# 四、前端也需要调整

当前前端过于强调“Copilot聊天”和视觉效果。招投标系统首先是业务工作台，不是聊天应用。

建议一级功能调整为：

```text
1. 项目总览
2. 招标文件中心
3. 招标要求矩阵
4. 资格与废标检查
5. 评分策略
6. 企业材料匹配
7. 产品与技术参数
8. 报价与成本
9. 投标文件编写
10. 审核与整改
11. 版本对比
12. 导出与封版
13. 智能助手
```

## 状态管理建议

* **TanStack Query**：管理服务器数据、缓存、刷新和失效；
* **Zustand**：仅管理当前选中页码、面板开关、临时编辑状态；
* **SSE**：更新TanStack Query缓存或触发重新查询。

不要把项目数据、报价表、章节正文、SSE事件全部塞入一个Zustand Store。

---

# 五、必须补充的数据实体

建议至少建立以下核心表：

```text
users
organizations
organization_members

bidding_projects
project_members
project_versions

source_documents
document_versions
document_blocks

requirements
requirement_versions
requirement_evidence_links

qualification_items
technical_items
commercial_items
scoring_items
risk_items

enterprise_assets
asset_versions
certificates
employees
employee_credentials
project_cases
products
product_certifications

response_items
cost_sheets
cost_items
proposal_sections
proposal_section_versions

review_tasks
review_comments
review_decisions

workflow_runs
workflow_node_runs
job_events

generated_artifacts
artifact_versions
audit_logs
```

所有AI生成结果至少要保留：

* 模型名称；
* Prompt版本；
* 输入块ID；
* 输出结果；
* 生成时间；
* Token消耗；
* 审核人；
* 修改记录；
* 最终采用版本。

---

# 六、测试体系需要从“代码覆盖率”升级为“业务可靠性”

当前测试设计只强调单元、集成、API和异步测试，还不够。

应增加：

## 1. 文档解析回归测试

准备固定招标文件样本，检查：

* 项目名称；
* 项目编号；
* 预算；
* 截止时间；
* 资格条件；
* 技术参数；
* 评分表；
* 表格；
* 下划线实质性条款。

## 2. Golden Dataset

人工标注一批标准答案：

```text
原始条款
正确分类
是否实质性
风险等级
对应评分项
正确页码
```

每次模型或Prompt更新都重新跑评测。

## 3. 一致性测试

自动检查：

* 开标一览表与报价汇总表金额一致；
* 大写金额与小写金额一致；
* 组件品牌全文一致；
* 型号全文一致；
* 工期全文一致；
* 质保期全文一致；
* 项目名称和编号全文一致；
* 人员姓名与证书一致；
* 每个评分项都有证据；
* 每个实质性要求都有响应。

## 4. 故障测试

模拟：

* LLM超时；
* Redis断开；
* MinIO不可用；
* OCR失败；
* Celery Worker重启；
* SSE断线重连；
* 重复上传；
* 同一任务重复执行；
* 导出过程中断。

---

# 七、推荐分阶段优化，不需要推倒重来

## 第一阶段：保留现有技术栈，修正核心边界

优先完成：

1. 建立 `Requirement` 响应矩阵。
2. 将报价计算从Cost Agent移出。
3. 将Word生成从Writer Agent移出。
4. 将主流程改为确定性LangGraph工作流。
5. `BiddingState`只保存ID和流程状态。
6. 增加人工审核节点。
7. Redis Pub/Sub改为Redis Streams或任务事件表。
8. API使用正确HTTP状态码。

这是最关键的一轮。

## 第二阶段：补足企业资产和投标生产能力

增加：

* 企业资质库；
* 人员库；
* 业绩库；
* 产品及检测报告库；
* 要求—证据自动匹配；
* DOCX模板渲染；
* 版本管理；
* 一致性校验；
* 评分模拟。

## 第三阶段：生产化

增加：

* 多租户；
* RBAC；
* 审计日志；
* 密钥管理；
* 文件病毒扫描；
* 模型网关；
* Prompt版本；
* Token和成本控制；
* OpenTelemetry；
* 容灾与备份；
* Golden Dataset评测。

---

# 最终判断

这份架构**可以作为开发起点，不建议废弃重做**。以下部分可以保留：

* FastAPI；
* Celery；
* LangGraph；
* PostgreSQL和pgvector；
* MinIO；
* React；
* SSE；
* 前后端基本分离；
* Agent节点无HTTP连接依赖的原则。

但必须调整四个核心设计：

1. **固定业务工作流替代Supervisor主导正式流程。**
2. **响应矩阵成为系统核心，而不是聊天和Agent。**
3. **确定性程序负责报价、校验和文档渲染。**
4. **AI输出必须绑定原文页码、企业证据、版本和人工审核。**

优化后，这套系统的定位才会从“能分析和生成文本的多Agent应用”，提升为：

> **以招标要求响应矩阵为核心，以企业证据库为基础，以规则引擎保证合规，以大模型辅助理解和写作，以人工审核控制最终承诺的投标文件生产系统。**
