# ChatAgent 面向国内模型 API 的对话持久化与上下文压缩方案

## 1. 文档信息

- **文档状态**：可实施方案（国内模型主路径首版已落地）
- **编制日期**：2026-09-07
- **适用范围**：`bidding_sys` 的前台 ChatAgent 对话系统
- **主要模型路径**：DeepSeek、GLM-5.3 等国内模型的 Chat Completions/OpenAI 兼容 API
- **相关模块**：ChatPanel、Chat API、ChatAgent、RAG、Agent 审计、租户隔离、模型配置

## 2. 方案结论

本项目可以实现类似 Codex 的长对话上下文压缩，但国内模型 API 的主路径不应依赖 OpenAI 原生 Responses compaction。应继续复用当前 LangGraph Agent，通过服务端自行管理会话、摘要和上下文预算。

推荐采用“服务端持久化 + 国内模型 Chat Completions 适配 + 通用结构化摘要”的分层方案，并将原生 compaction 作为可选能力：

1. 服务端保存完整、可审计、与模型无关的原始对话记录。
2. 使用稳定的 `session_id` 区分同一文档下的多个独立会话。
3. 使用 checkpoint 管理模型实际使用的工作上下文，压缩不删除原始记录。
4. 以 Chat Completions、Function Calling、JSON 输出和流式输出作为 DeepSeek、GLM-5.3 的共同能力基线。
5. 以应用侧结构化摘要作为国内模型的主要压缩方式，压缩不删除原始消息。
6. 只有 provider/model 能力注册表明确确认支持时，才启用原生 Responses compaction；它不是国内模型路径的前置条件。
7. 招标文件、企业资质、报价、BOM 和合同条款仍以 RAG 或业务数据库为事实来源，不能由摘要替代。

## 3. 当前实现与问题边界

当前实现位于：

- `backend/app/agents/chat_agent.py`
- `backend/app/api/endpoints/chat.py`
- `frontend/src/components/ChatPanel.tsx`
- `backend/app/services/llm_service.py`

以下现状描述的是本次改造前基线；首版已按后文的国内模型主路径完成会话持久化、上下文摘要和前端会话切换接线：

1. `ChatAgent` 使用 LangGraph `create_react_agent` 和 `astream_events` 进行 ReAct 工具调用与 SSE 输出。
2. 后端当前只取 `history` 的最近 10 条消息，无法根据真实 token 使用量动态管理上下文。
3. 每一轮请求都生成随机 `chat_task_id`，它适合作为审计任务 ID，不适合作为长期会话 ID。
4. 前端主要按 `document_id` 将历史保存到 `localStorage`，一份文档只有一份本地历史，无法支持多个独立会话。
5. 改造前项目没有 ChatSession、ChatMessage 或上下文 checkpoint 数据表；首版已新增对应模型和 Alembic 迁移。
6. `llm_service` 使用 `ChatOpenAI` 并支持租户级动态模型配置，同时兼容 OpenAI 兼容接口。DeepSeek 和 GLM-5.3 可以作为 Chat Completions 模型接入，但不能仅凭“OpenAI 兼容”假设它们支持 Responses API 或原生 compaction。

这些问题决定了本方案必须先建立项目自己的会话和状态边界，再接入模型相关的压缩能力。

## 4. 核心概念与 ID 规则

### 4.1 三类 ID

| ID | 生命周期 | 用途 | 是否稳定 |
|---|---|---|---|
| `document_id` | 文档生命周期 | 指定 RAG 和业务查询的知识范围 | 稳定 |
| `session_id` | 一次独立对话 | 保存和恢复同一段多轮会话 | 稳定 |
| `chat_task_id` | 单轮请求 | 记录本轮 Agent 执行、工具调用和耗时 | 每轮随机 |

约束：

- 一个 `document_id` 可以关联多个 `session_id`。
- 一个 `session_id` 只能属于一个租户、一个用户和一个文档。
- `chat_task_id` 不能用于恢复对话。
- 租户和用户身份必须从服务端认证上下文获取，不能信任请求体中的租户字段。

### 4.2 对话与上下文分离

```text
永久事实层：原始消息、工具审计、引用来源
        ↓
可迁移状态层：结构化摘要、任务进度、关键决策
        ↓
模型工作层：近期消息、RAG 结果、模型专属 checkpoint
```

永久事实层用于历史查询和审计；模型工作层只用于构造下一次请求。

## 5. 目标架构

```text
ChatPanel
   ↓ session_id + document_id + question
Chat API
   ↓ 鉴权、文档权限、会话归属校验
ChatSessionService
   ↓ 读取会话、消息和最新 checkpoint
ContextManager
   ├─ 未达到阈值：checkpoint + 增量消息
   ├─ 达到阈值：完成当前回合后生成结构化摘要
   └─ 明确支持时：可选原生 Responses compaction
   ↓
DomesticModelAdapter / ChatAgent
   ├─ DeepSeek Chat Completions
   ├─ GLM-5.3 Chat Completions
   └─ 其他 OpenAI 兼容模型
   ↓
RAG、结构化提取工具、企业业务工具
   ↓
消息持久化、引用持久化、AgentAuditLog
```

## 6. 数据模型设计

### 6.1 `chat_sessions`

用于保存独立会话，不保存完整消息正文。

建议字段：

| 字段 | 说明 |
|---|---|
| `id` | `session_id`，建议 UUID |
| `tenant_id` | 租户隔离字段 |
| `user_id` | 创建者或当前会话用户 |
| `document_id` | 当前招标文件 |
| `title` | 会话标题，可由首个问题生成并允许修改 |
| `status` | `active`、`archived`、`deleted` |
| `latest_checkpoint_id` | 当前工作上下文 checkpoint |
| `active_provider` | 当前使用的模型提供商 |
| `active_model` | 当前使用的模型名称或版本 |
| `context_format_version` | 上下文格式版本 |
| `created_at` | 创建时间 |
| `updated_at` | 最后活动时间 |

不建议对 `(user_id, document_id)` 建立唯一约束，因为同一用户在同一文档下需要拥有多个会话。

### 6.2 `chat_messages`

保存完整原始聊天记录，模型切换和历史展示均以此为基础。

建议字段：

| 字段 | 说明 |
|---|---|
| `id` | 消息 ID |
| `session_id` | 所属会话 |
| `sequence` | 会话内递增序号 |
| `role` | `user`、`assistant`、`tool` |
| `content` | 文本内容或标准化 JSON 内容 |
| `tool_name` | 工具消息使用 |
| `tool_arguments` | 工具调用参数 |
| `tool_call_id` | 工具调用关联 ID |
| `provider_payload_json` | 可选保存 provider 原始消息字段，用于同一 provider 重放 |
| `sources_json` | 助手回答引用来源 |
| `status` | `streaming`、`completed`、`failed` |
| `token_count` | 已知时保存 token 数 |
| `created_at` | 创建时间 |

前端的 `ai` 角色应在 API 边界映射为内部统一的 `assistant` 角色，避免把前端字段直接作为模型协议。

`provider_payload_json` 仅用于同一 provider 的审计或重放，不能作为跨模型上下文。DeepSeek 的 `reasoning_content`、GLM 的推理字段等 provider 专属字段默认不进入通用摘要；如因同 provider 工具调用恢复确需保存，应加密保存并遵循敏感数据保留策略。

### 6.3 `chat_context_checkpoints`

用于保存压缩后的模型工作上下文。

建议字段：

| 字段 | 说明 |
|---|---|
| `id` | checkpoint ID |
| `session_id` | 所属会话 |
| `upto_sequence` | 已覆盖到的消息序号 |
| `strategy` | `summary` 或 `native` |
| `provider` | 生成 checkpoint 的提供商 |
| `model` | 生成 checkpoint 的模型 |
| `protocol` | `chat_completions` 或 `responses` |
| `capability_snapshot` | 生成时的模型能力快照 |
| `payload` | 结构化摘要或原生 compaction item |
| `token_count` | checkpoint 占用 token |
| `created_at` | 创建时间 |

`summary` checkpoint 是国内模型的默认方案，必须使用项目自定义的、跨 provider 的结构化格式。原生 compaction 的 `encrypted_content` 只在明确支持的 provider 上使用，必须作为不透明字符串保存，不能解析、修改或拼接。OpenAI 官方文档明确说明该内容不可读，压缩后的窗口应作为后续请求的 canonical context 使用：

- [OpenAI Compaction 指南](https://developers.openai.com/api/docs/guides/compaction)
- [OpenAI Conversation State 指南](https://developers.openai.com/api/docs/guides/conversation-state)
- [DeepSeek Responses API 兼容性说明](https://api-docs.deepseek.com/guides/responses_api/)
- [GLM-5.3 Chat Completion API](https://docs.z.ai/api-reference/llm/chat-completion)

### 6.4 Agent 工具审计

第一阶段继续复用现有 `AgentAuditLog` 保存工具调用、输入输出、耗时和错误信息，不立即重复建立 `chat_tool_events` 表。

但必须通过 `chat_task_id`、`session_id`、`document_id`、`user_id` 和 `tenant_id` 建立关联，避免审计记录无法定位到具体会话。

## 7. 会话生命周期

### 7.1 继续已有会话

1. 前端发送 `session_id`、`document_id` 和当前问题。
2. 后端校验当前用户是否拥有该会话，以及会话是否属于该文档。
3. 读取最新 checkpoint。
4. 加载 checkpoint 之后的新消息。
5. 构造 Agent 输入并执行。
6. 流式结束后保存最终回答和引用来源。

### 7.2 当前文档新建会话

1. 前端以当前 `document_id` 调用创建会话接口。
2. 后端创建新的 `session_id`。
3. 新会话不复制旧会话的消息和 checkpoint。
4. 新会话仍然可以通过相同文档的 RAG 和业务工具查询事实。
5. 前端切换当前活动会话并清空展示区。

### 7.3 从旧会话分叉

只有用户明确选择“基于此对话继续”时才执行分叉：

1. 创建新的 `session_id`。
2. 复制旧会话的通用结构化状态和必要的近期消息。
3. 不直接复制旧模型的 native checkpoint。
4. 记录 `parent_session_id`，方便追溯和回滚。

## 8. 上下文构建与压缩策略

### 8.1 上下文组成

每一轮模型调用的上下文由以下部分组成：

```text
系统规则与当前文档范围
+ 最新 checkpoint
+ checkpoint 之后的近期对话
+ 当前问题
+ 当前轮工具结果
+ 必要的 RAG 引文
```

历史消息全部保存，但不全部发送给模型。

### 8.2 第一阶段：结构化摘要压缩

当前 LangGraph 和多模型环境优先使用结构化摘要，摘要格式建议包含：

```text
当前任务目标
已确认的对话事实
已完成工作
关键决策及原因
已调用工具及结果摘要
引用来源标识
未完成事项
下一步建议
```

压缩流程：

1. 通过 token 计数器估算当前上下文大小。
2. 达到配置阈值后触发压缩。
3. 仅将必要的历史和近期工具结果交给摘要器。
4. 保存新的 `summary` checkpoint。
5. 将 checkpoint 覆盖范围记录为 `upto_sequence`。
6. 后续只加载 checkpoint 之后的增量消息。

摘要压缩是有损的，因此重要的招标事实必须保留来源 ID，并允许后续通过 RAG 重新取回原文。

### 8.3 国内模型主路径：Chat Completions 与结构化摘要

DeepSeek 和 GLM-5.3 的共同基线是基于 `messages` 的 Chat Completions、函数工具调用、JSON 输出和流式输出。因此，国内模型不需要切换到 Responses Runtime 即可实现本方案的会话恢复和上下文压缩：

- DeepSeek 官方 API 支持 Function Calling、JSON Output、流式输出和 token usage；
- GLM-5.3 官方 API 支持 `messages`、函数工具、工具调用流式输出、JSON 输出和 token usage；
- 两者的上下文缓存只能降低重复前缀的计算成本，不能代替应用侧摘要压缩；
- provider 的 token 计数、推理字段和错误行为存在差异，必须通过适配器隔离。

参考文档：

- [DeepSeek Tool Calls](https://api-docs.deepseek.com/guides/tool_calls/)
- [DeepSeek JSON Output](https://api-docs.deepseek.com/guides/json_mode/)
- [DeepSeek Context Caching](https://api-docs.deepseek.com/guides/kv_cache/)
- [GLM-5.3 Chat Completion](https://docs.z.ai/api-reference/llm/chat-completion)
- [GLM Function Calling](https://docs.z.ai/guides/capabilities/function-calling)

国内模型的压缩流程：

1. 根据 provider 返回的 `usage` 和本地估算计算上下文预算，并预留输出与推理 token。
2. 只有在一轮 Agent 完整结束、没有未完成的工具调用时才允许压缩。
3. 保留工具调用与工具结果的完整配对，不截断半个工具调用链。
4. 调用结构化摘要器生成固定 schema 的摘要；优先使用 provider 的 JSON 输出能力。
5. 校验摘要 schema、来源 ID、文档 ID 和待办事项，失败时保留旧 checkpoint 并记录日志。
6. 保存新的 `summary` checkpoint，后续发送“摘要 + checkpoint 后的近期消息 + 当前问题”。

摘要器可以使用当前模型，也可以使用租户配置的低成本模型，但摘要格式必须由项目控制，不能依赖某个模型的私有上下文格式。

### 8.4 可选：原生 Responses compaction

只有满足以下条件时才启用：

- 当前提供商确实支持 Responses API；
- 当前模型和接口明确支持 `context_management` 或等价的 compaction 参数；
- 工具调用已完成 Responses API 格式适配；
- `encrypted_content` 可以安全保存和恢复；
- 已有从原始消息重建上下文的降级路径。

当前国内模型处理原则：

| 模型 | 官方接口现状 | 本项目处理方式 |
|---|---|---|
| DeepSeek | 提供 Responses API 格式，但官方明确 `context_management`、`previous_response_id`、`truncation` 不支持，接口无状态 | 使用 Chat Completions + 结构化摘要，不启用 native |
| GLM-5.3 | 官方公开接口以 Chat Completions 为主，支持函数调用和流式工具调用，未公开 `context_management`/compaction 参数 | 使用 Chat Completions + 结构化摘要；除非具体网关另有明确文档 |
| OpenAI 或其他 provider | 以实际接口能力为准 | 通过能力注册表确认后再启用 |

“OpenAI 兼容”只代表请求格式相似，不能证明支持原生 compaction。原生 checkpoint 应标记为模型专属状态，不能当作跨模型通用记忆。

### 8.5 工具输出控制

工具输出是上下文增长的主要来源之一。应：

- 优先返回结构化结果和必要证据；
- 避免把大段重复原文直接放入每轮上下文；
- 对单个工具输出设置上限；
- 需要全文时保存引用位置，后续按需重新读取。

Codex 当前配置参考中也提供了 `tool_output_token_limit`、`model_auto_compact_token_limit` 和 `model_context_window` 等相关配置项，可作为本项目配置设计的参考：[Codex 配置参考](https://learn.chatgpt.com/docs/config-file/config-reference)。

## 9. 模型适配与切换兼容策略

### 9.1 原则

```text
原始消息和通用摘要可迁移
provider_payload 和 reasoning 字段默认不可跨模型迁移
native compaction 不保证可迁移
```

这是基于原生 compaction item 不透明、不同 provider 的工具协议和推理字段不同而采取的保守工程策略。

### 9.2 国内模型适配器

建议将模型能力集中声明，不在 `ChatAgent` 内散落 provider 判断：

```text
ModelCapabilities
├─ protocol: chat_completions / responses
├─ supports_tools
├─ supports_json_output
├─ supports_streaming_tools
├─ supports_native_compaction
├─ preserve_reasoning_fields
├─ context_window
├─ tokenizer
└─ reasoning_policy
```

适配器至少负责：消息角色映射、工具调用字段、流式事件、JSON 输出、token usage、上下文窗口和 provider 特有推理字段。DeepSeek 思考模式结合工具调用时，需要按官方要求完整传递后续请求所需的 `reasoning_content`；GLM-5.3 的历史推理字段则受 `clear_thinking` 等参数影响。两者都不能由通用 LangChain 消息转换逻辑直接猜测。

### 9.3 切换流程

当租户修改模型配置时：

1. 记录模型切换事件。
2. 保留原始 `chat_messages` 和旧 checkpoint。
3. 如果旧 checkpoint 是 `native`，将其标记为旧模型专属，不再直接使用。
4. 如果旧 provider 存在 `reasoning_content` 或其他专属字段，不将其作为跨模型上下文发送；仅在旧 provider 的未完成工具调用恢复中使用。
5. 使用通用摘要、近期可见消息和当前文档 RAG 重新构建上下文。
6. 使用新模型继续会话，并执行工具调用、JSON 输出和流式输出兼容性检查。
7. 新模型稳定运行后生成新的 `summary` checkpoint。

同一个 `session_id` 可以继续使用，但必须更新 `active_provider`、`active_model` 和 `context_format_version`。

如果模型从 LangGraph/Chat Completions 路径切换到 Responses 路径，建议建立独立 runtime，不要把原生 compaction item、DeepSeek `reasoning_content` 或 GLM 专属推理字段塞入跨模型通用的 LangChain `BaseMessage`。

## 10. API 方案

### 10.1 会话接口

```text
POST /api/v1/chat/sessions
GET  /api/v1/chat/sessions?document_id={document_id}
GET  /api/v1/chat/sessions/{session_id}/messages
PATCH /api/v1/chat/sessions/{session_id}
POST /api/v1/chat/sessions/{session_id}/archive
```

非流式接口继续使用项目统一的 `code`、`message`、`data` 响应格式。

### 10.2 流式聊天接口

```json
{
  "document_id": "文档 ID",
  "session_id": "可选；首次请求可以为空",
  "question": "用户问题"
}
```

首次请求没有 `session_id` 时，后端创建会话，并通过 SSE 首个事件返回：

```json
{
  "type": "session",
  "session_id": "新会话 ID"
}
```

之后的请求只发送 `session_id` 和当前问题，不再依赖前端传递完整 `history`。

## 11. SSE 与失败恢复

### 11.1 保存时机

建议按以下顺序处理：

1. 请求进入后保存用户消息，状态为 `streaming`。
2. Agent 执行期间继续写入工具审计。
3. SSE 正常结束后保存助手完整回答、来源和 token 信息。
4. 将助手消息更新为 `completed`。
5. 异常或客户端中断时将助手消息更新为 `failed`，保留错误原因和已生成内容摘要。

### 11.2 并发控制

同一个 `session_id` 同时只允许一个活动响应，建议增加：

- 数据库行锁或 Redis 分布式锁；
- 请求幂等键；
- 流式请求超时后的锁释放；
- 失败消息重试或重新生成入口。

即使前端当前禁止重复发送，后端也必须进行会话级并发保护。

## 12. 前端改造

当前按文档保存单份历史：

```text
chat_history_{document_id}
```

建议调整为：

```text
chat_sessions_{document_id}
active_chat_session_{document_id}
chat_messages_{session_id}
```

前端功能包括：

1. 当前文档的会话列表。
2. 新建会话。
3. 切换会话。
4. 会话重命名和归档。
5. 历史消息分页加载。
6. SSE 中断后显示失败状态并支持重试。

`localStorage` 只作为界面缓存，服务端数据库才是会话真相源。旧的 `chat_history_{document_id}` 可在升级后首次读取并迁移为该文档下的第一个会话。

## 13. 事实、权限与安全边界

### 13.1 权限校验

每次读取或写入会话都必须同时校验：

```text
session.tenant_id == current_user.tenant_id
session.user_id == current_user.id 或用户具有共享权限
session.document_id == 请求 document_id
当前用户有权访问 document_id
```

不允许仅凭 `session_id` 直接读取数据。

### 13.2 事实来源优先级

```text
招标文件原文 / 企业业务数据库
        > 当前工具查询结果与审计结论
        > 历史会话摘要
```

历史摘要不能覆盖当前文档中的新事实，不能直接提供未经当前数据源验证的金额、日期、证书编号或技术参数。

### 13.3 敏感数据

- 数据库中的会话和 checkpoint 必须遵循租户隔离。
- 原生 compaction item 虽然不可读，仍应按敏感数据保护。
- 日志中禁止输出完整 API Key、完整提示词或不必要的招标原文。
- 摘要器不得把工具注入的指令性文本当作系统规则。

## 14. 分阶段实施计划

### Phase 0：模型能力注册与兼容性验证

目标：把国内模型的协议差异收敛在适配层。

- 建立 `ModelCapabilities` 配置和 provider/model 白名单；
- 明确 DeepSeek、GLM-5.3 的 Chat Completions、工具调用、JSON 输出、流式输出和 token usage 能力；
- 对 `reasoning_content`、`clear_thinking`、工具消息配对和上下文超限分别建立适配规则；
- 增加真实 API 的最小冒烟测试，禁止仅根据 `base_url` 或模型名称判断能力。

### Phase 1：持久化基础

目标：支持完整记录和同文档多会话。

- 新增 `chat_sessions`、`chat_messages` 模型和迁移；
- 增加会话 CRUD；
- 增加 `session_id` 请求字段；
- 将 `chat_task_id` 与 `session_id` 分离；
- 前端增加会话列表和新建会话；
- 保留旧前端历史迁移逻辑。

### Phase 2：服务端上下文管理

目标：不再依赖前端完整 history。

- 新增 `ChatSessionService`；
- 新增 `ContextManager`；
- 读取最新 checkpoint 加增量消息；
- 增加 token 计数器接口；
- 增加工具输出上限；
- 增加会话级并发锁和失败恢复。

### Phase 3：国内模型通用结构化摘要压缩

目标：兼容现有 LangGraph、DeepSeek、GLM-5.3 和其他 Chat Completions API。

- 新增 `chat_context_checkpoints`；
- 实现结构化摘要生成和校验；
- 保存来源 ID、文件 ID、章节信息和待办事项；
- 使用 provider 实际 token usage 和上下文窗口计算压缩阈值；
- 完成 DeepSeek、GLM-5.3 的工具调用与摘要恢复测试；
- 增加压缩前后上下文回归测试；
- 压缩后继续使用现有 ChatAgent。

### Phase 4：模型切换适配

目标：租户切换模型时不丢失会话。

- 保存 provider、model 和 context format；
- 模型切换时停用旧 provider 专属 checkpoint 和推理字段；
- 从原始消息和通用摘要重建上下文；
- 为不同模型建立能力声明和 token 计数器；
- 增加跨模型恢复测试。

### Phase 5：可选原生 Responses compaction

目标：对未来明确支持原生 compaction 的 provider/model 使用原生压缩，不影响国内模型主路径。

- 新增 Responses runtime 或独立适配器；
- 完成工具调用格式转换；
- 保存不透明的 native checkpoint；
- 实现 native 失败时回退到结构化摘要；
- 验证模型切换、会话恢复和多租户隔离。

## 15. 测试与验收标准

测试代码应按照现有目录规范放置：

- 单元测试：`backend/tests/unit/`
- API 测试：`backend/tests/api/`
- 集成测试：`backend/tests/integration/`
- 测试数据：`backend/tests/fixtures/`

至少覆盖：

1. 同一文档创建多个会话，消息互不串联。
2. 不同租户不能读取或写入其他租户会话。
3. 同一会话可以跨请求恢复。
4. 压缩后可以继续调用工具并生成回答。
5. 原始消息不会因为压缩而删除。
6. SSE 正常结束、客户端中断和 Agent 异常均能正确记录状态。
7. 模型切换后可以从通用状态恢复。
8. native checkpoint 不会被错误地交给不兼容模型。
9. 文档切换后不会加载旧文档会话。
10. 旧版 `localStorage` 历史可以迁移到新会话。
11. DeepSeek 工具调用回合的 provider 推理字段不会被错误截断。
12. GLM-5.3 工具调用、JSON 输出和流式工具参数可以完成闭环。
13. DeepSeek 和 GLM-5.3 不会因为被误判支持 native compaction 而发送未支持参数。
14. 国内模型上下文超限前能够触发摘要或明确返回可恢复错误。

最终验收应满足：

```text
同一文档支持多个独立会话
+ 完整记录可恢复
+ 上下文可自动压缩
+ 模型可切换
+ 原始事实不被摘要覆盖
+ 租户和文档权限不越界
```

## 16. 风险与应对

| 风险 | 应对方案 |
|---|---|
| 摘要遗漏关键细节 | 保存来源 ID；关键事实通过 RAG 重新查询 |
| 模型切换后 native checkpoint 不兼容 | native checkpoint 标记 provider/model，切换时从通用状态重建 |
| 工具输出导致上下文快速膨胀 | 工具输出上限、结构化结果、按需全文读取 |
| SSE 中断造成消息不完整 | 消息状态机、失败记录、幂等重试 |
| 前端 history 被篡改 | 后端以数据库会话为准，不信任完整 history |
| 同一会话并发请求互相覆盖 | 会话级锁和请求幂等键 |
| RAG 事实被旧摘要污染 | 强制当前文档工具和业务数据库优先 |
| DeepSeek 思考模式工具调用缺少 `reasoning_content` | provider 适配器保留未完成回合所需字段；压缩只发生在完整回合之后 |
| GLM-5.3 推理字段被错误复用 | 默认不跨模型迁移 provider 推理字段，按 `clear_thinking` 策略构造历史 |
| 不同模型 tokenizer 和上下文窗口不一致 | 使用能力注册表、provider usage 和保守阈值，不依赖单一 tokenizer |
| 国内模型 JSON 输出为空或被截断 | schema 校验、重试、降级为文本解析，并保留旧 checkpoint |

## 17. 推荐的最终落地选择

当前项目应优先实施：

```text
服务端会话持久化
    ↓
同一文档多会话
    ↓
DeepSeek / GLM-5.3 Chat Completions 适配层
    ↓
结构化摘要 checkpoint
    ↓
模型切换重建上下文
    ↓
对明确兼容的 provider 增加可选原生 Responses compaction
```

不要第一步就替换现有 LangGraph Agent，也不要把 DeepSeek 或 GLM-5.3 强行改造成 Responses Runtime。先将“历史记录”“通用状态”“provider 专属消息字段”和“可选 native checkpoint”分层，国内模型即可落地长对话、多会话、自动摘要压缩和跨模型恢复。
