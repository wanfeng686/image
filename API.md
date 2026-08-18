# SmartSupport · 前后端接口契约文档（API.md）

> 依据 [DESIGN.md](./DESIGN.md) §10 展开的前后端分离接口契约。
> 前端（11 页面）与后端（FastAPI）按本文档并行开发；字段以本文档为准，与 DESIGN.md 冲突时以本文档为准。

- **版本**: v1.0
- **日期**: 2026-08-14
- **状态**: 契约定稿，开发依据

---

## 目录

1. [通用约定](#1-通用约定)
2. [页面 ↔ 接口映射总表](#2-页面--接口映射总表)
3. [认证接口](#3-认证接口)
4. [顾客端接口（P1 Widget）](#4-顾客端接口p1-widget)
5. [SSE 事件协议](#5-sse-事件协议)
6. [运营台 · 概览（P2）](#6-运营台--概览p2)
7. [运营台 · 会话（P3）](#7-运营台--会话p3)
8. [运营台 · 审批（P4）](#8-运营台--审批p4)
9. [运营台 · 知识库（P5）](#9-运营台--知识库p5)
10. [运营台 · 洞察日报（P6）](#10-运营台--洞察日报p6)
11. [设置 · 模型配置（P7）](#11-设置--模型配置p7)
12. [设置 · Agent管理与提示词（P8）](#12-设置--agent管理与提示词p8)
13. [设置 · 审批与风险规则（P9）](#13-设置--审批与风险规则p9)
14. [设置 · 升级硬规则（P10）](#14-设置--升级硬规则p10)
15. [设置 · 工具权限矩阵（P11）](#15-设置--工具权限矩阵p11)
16. [Eval 接口](#16-eval-接口)
17. [管理接口（演示/登录）](#17-管理接口演示)
18. [附录A：DTO 模型](#附录a-dto-模型)
19. [附录B：枚举值表](#附录b-枚举值表)
20. [附录C：错误码表](#附录c-错误码表)

---

## 1. 通用约定

| 项 | 约定 |
|---|---|
| Base URL | `/api` |
| 数据格式 | `Content-Type: application/json`（文件上传除外）；SSE 为 `text/event-stream` |
| 字段命名 | 一律 **snake_case**（与后端 Python/DB 一致，前端不做驼峰转换） |
| 时间格式 | ISO 8601 UTC，如 `2026-08-14T06:00:00Z` |
| ID 格式 | UUID v4 字符串 |
| 分页请求 | `?page=1&page_size=20`（page_size 上限 100） |
| 分页响应 | 统一包裹：`{"items": [...], "total": 123, "page": 1, "page_size": 20}` |
| 认证-运营台 | `Authorization: Bearer <JWT>`（登录见 §3） |
| 认证-顾客端 | `X-Session-Token: <token>`（创建会话时返回，见 §4.1） |

**统一错误响应格式：**

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "人话描述",
    "detail": { "field": "amount", "reason": "必须为正数" }
  }
}
```

**HTTP 状态码使用：** 200 成功 ｜ 201 创建 ｜ 400 参数错误 ｜ 401 未认证 ｜ 403 无权限 ｜ 404 不存在 ｜ 409 冲突（幂等/状态冲突）｜ 422 语义错误 ｜ 429 限流 ｜ 500 服务端错误

**写操作幂等（仅资金相关）：** 审批类接口支持 `Idempotency-Key` 请求头，重复提交返回首次结果。

---

## 2. 页面 ↔ 接口映射总表

| 页面 | 用到的接口 |
|---|---|
| P0 落地页 | `GET /demo/stats` ｜ `POST /admin/demo/reset`（演示模式） |
| P1 顾客 Widget | `POST /chat/sessions` ｜ `GET /chat/sessions/{id}` ｜ `POST /chat/sessions/{id}/messages` ｜ `GET /chat/sessions/{id}/stream` ｜ `POST /chat/sessions/{id}/rate` ｜ `POST /chat/sessions/{id}/escalate` |
| P2 概览 | `GET /console/dashboard/overview` |
| P3 会话 | `GET /console/sessions` ｜ `GET /console/sessions/{id}` ｜ `POST .../takeover` ｜ `POST .../notes` ｜ `POST .../replay` ｜ `GET .../export` ｜ `GET /console/stream`（实时） |
| P4 审批 | `GET /console/approvals` ｜ `GET /console/approvals/{id}` ｜ `POST .../approve` `reject` `return` `remind` ｜ `POST /console/approvals/batch-approve` ｜ `GET /console/stream` |
| P5 知识库 | `GET/POST /console/kb/documents` ｜ `GET/PUT /console/kb/documents/{id}` ｜ `POST .../publish` `offline` `import` ｜ `GET .../versions` ｜ `POST .../versions/{vid}/rollback` ｜ `GET /console/kb/gaps` ｜ `POST /console/kb/gaps/{id}/generate-draft` `ignore` `reattribute` ｜ `GET /console/kb/drafts` ｜ `PUT /console/kb/drafts/{id}` ｜ `POST .../adopt` `reject` |
| P6 洞察日报 | `GET /console/insights` ｜ `POST /console/insights/regenerate` ｜ `POST /console/insights/findings/{id}/apply` `ignore` ｜ `POST /console/insights/subscribe` |
| P7 模型配置 | `GET/POST /console/settings/providers` ｜ `GET/PUT/DELETE /console/settings/providers/{id}` ｜ `POST .../test` ｜ `GET /console/settings/bindings` ｜ `PUT /console/settings/bindings/{agent}` ｜ `POST /console/settings/bindings/apply-preset` ｜ `GET /console/settings/bindings/estimate` ｜ `GET/PUT /console/settings/rag-models` |
| P8 提示词 | `GET /console/settings/agents` ｜ `GET /console/settings/agents/{agent}/prompts` ｜ `POST /console/settings/agents/{agent}/prompts` ｜ `GET/PUT /console/settings/prompts/{id}` ｜ `POST /console/settings/prompts/{id}/publish` ｜ `POST /console/settings/prompts/{id}/rollback` ｜ `GET /console/settings/prompts/{id}/diff` ｜ `POST /console/settings/agents/{agent}/playground` |
| P9 风险规则 | `GET/PUT /console/settings/risk` |
| P10 升级规则 | `GET/POST /console/settings/escalation` ｜ `PUT/DELETE /console/settings/escalation/{id}` ｜ `PUT /console/settings/escalation/reorder` |
| P11 权限矩阵 | `GET /console/settings/permissions` ｜ `PUT /console/settings/permissions/{agent}` |
| 跨页面 | `POST /auth/login` ｜ `GET /auth/me` ｜ `GET /console/stream` ｜ `POST /console/eval/run` ｜ `GET /console/eval/runs` |

---

## 3. 认证接口

### POST /auth/login — 运营台登录
```json
// Request
{ "username": "admin", "password": "******" }
// 200
{ "token": "eyJhbGciOi...", "operator": { "id": "uuid", "display_name": "管理员", "role": "admin" } }
// 401
{ "error": { "code": "AUTH_FAILED", "message": "用户名或密码错误" } }
```

### GET /auth/me — 当前用户
```json
// 200
{ "id": "uuid", "display_name": "管理员", "role": "admin", "is_online": true }
```

---

## 4. 顾客端接口（P1 Widget）

顾客端无需账号，创建会话即获得 `session_token`，后续请求带 `X-Session-Token` 头。

### 4.1 POST /chat/sessions — 创建会话
```json
// Request
{ "nickname": "访客7291" }               // 可选；演示模式可传 "demo_scenario": "refund"
// 201
{
  "session_token": "st_9f8e7d6c",
  "session": {
    "id": "uuid", "status": "active", "created_at": "2026-08-14T02:00:00Z"
  }
}
```

### 4.2 GET /chat/sessions/{id} — 恢复会话（刷新页面/断线重连）
```json
// 200
{
  "session": { "id": "uuid", "status": "waiting_approval", "satisfaction": null },
  "messages": [
    { "id": "uuid", "role": "customer", "content": "我的订单什么时候到", "content_type": "text", "created_at": "..." },
    { "id": "uuid", "role": "agent", "content": "...", "content_type": "card",
      "card_data": { "type": "order", "order_no": "1024", "status": "shipped", "eta": "2026-08-15" },
      "agent_source": "order", "created_at": "..." }
  ]
}
```

### 4.3 POST /chat/sessions/{id}/messages — 发送消息
```json
// Request
{ "content": "我要退款，物流太慢了", "client_msg_id": "c-123" }   // client_msg_id 用于前端去重
// 202 （消息已接收，AI 处理中；内容通过 SSE 流式返回）
{ "message": { "id": "uuid", "role": "customer", "status": "accepted" }, "stream_url": "/api/chat/sessions/{id}/stream" }
// 409 SESSION_CLOSED
```

### 4.4 GET /chat/sessions/{id}/stream — SSE 流（协议见 §5）

### 4.5 POST /chat/sessions/{id}/rate — 满意度评价
```json
// Request  { "rating": 1 }        // 1=👍  -1=👎
// 200      { "session": { "id": "uuid", "satisfaction": 1 } }
```

### 4.6 POST /chat/sessions/{id}/escalate — 用户点"转人工"（铁律：直转）
```json
// 200
{ "session": { "id": "uuid", "status": "escalated", "escalated_reason": "user_request" } }
```

---

## 5. SSE 事件协议

### 5.1 顾客端流 `GET /chat/sessions/{id}/stream`

`Accept: text/event-stream`。每个事件格式：

```
event: agent_status
data: {"agent": "order", "status": "working"}
```

| 事件 | data 结构 | 前端行为 |
|---|---|---|
| `turn_start` | `{"message_id": "uuid"}` | 开始一轮处理 |
| `agent_status` | `{"agent": "order", "status": "working"\|"done"\|"failed", "run_id": "uuid"}` | **驱动 Agent 状态条**：显示对应颜色脉冲动画（颜色由前端 `agentColors.ts` 按 agent 名映射） |
| `message_delta` | `{"message_id": "uuid", "delta": "您"}` | 逐字追加到气泡 |
| `card` | `{"message_id": "uuid", "card_data": {...}}` | 渲染数据卡片（订单/退款卡） |
| `message_completed` | `{"message": {完整 message 对象}}` | 定格气泡，替换增量内容 |
| `approval_pending` | `{"approval_id": "uuid", "summary": "退款 ¥299 待审批", "timeout_at": "..."}` | 显示琥珀色"等待人工审批"横幅 |
| `session_status` | `{"status": "waiting_approval"\|"escalated"\|"active"\|"closed"}` | 更新会话状态 UI |
| `escalated` | `{"reason": "keyword"\|"user_request"\|...}` | 提示"已转接人工客服" |
| `error` | `{"code": "BUDGET_EXCEEDED", "message": "..."}` | 错误提示 |
| `turn_end` | `{"message_id": "uuid", "stats": {"duration_ms": 8200, "cost": 0.031}}` | 一轮结束 |
| `ping` | `{}` | 心跳，15s 一次，前端据此判断断线重连 |

### 5.2 运营台流 `GET /console/stream`（JWT）

| 事件 | data 结构 | 前端行为 |
|---|---|---|
| `approval.created` | `{approval: {审批对象}}` | P4 队列插入新卡片 + 角标+1 |
| `approval.resolved` | `{approval_id, status}` | P4 更新卡片状态 |
| `session.updated` | `{session_id, status}` | P3 列表状态刷新 |
| `message.created` | `{session_id, message}` | P3 打开的会话实时追加消息 |
| `agent_run.created` | `{session_id, run: {AgentRun对象}}` | P3 轨迹时间线实时追加步骤 |
| `insight.ready` | `{report_date}` | P6 提示"今日报告已生成" |
| `ping` | `{}` | 心跳 |

---

## 6. 运营台 · 概览（P2）

### GET /console/dashboard/overview?range=today|7d|30d
```json
// 200
{
  "kpis": {
    "sessions": 123, "auto_resolution_rate": 0.71, "escalation_rate": 0.12,
    "qc_rejection_rate": 0.08, "cost": 3.42, "satisfaction": 0.82
  },
  "charts": {
    "trend":        [{ "date": "2026-08-13", "sessions": 100, "resolved": 71, "escalated": 12 }],
    "intents":      [{ "intent": "refund", "count": 45 }],
    "agent_calls":  [{ "agent": "knowledge", "count": 210, "avg_latency_ms": 1200 }],
    "model_cost":   [{ "agent": "knowledge", "model": "deepseek-chat", "cost": 1.20 }]
  }
}
```

---

## 7. 运营台 · 会话（P3）

### GET /console/sessions?status=active|waiting_approval|escalated|closed&q=关键词&page=1
```json
// 200
{ "items": [{
    "id": "uuid", "user": { "nickname": "张**", "user_tier": "normal" },
    "status": "waiting_approval", "last_intent": { "intents": ["refund"], "sentiment": 2.1 },
    "satisfaction": null, "message_count": 12, "has_pending_approval": true,
    "last_message_at": "...", "created_at": "..."
}], "total": 57, "page": 1, "page_size": 20 }
```

### GET /console/sessions/{id} — 会话详情（对话流 + Agent 轨迹）
```json
// 200
{
  "session": { "id": "uuid", "status": "waiting_approval", "rolling_summary": "...",
    "slots": { "last_order_id": "1024" }, "sentiment": 2.1,
    "escalated_reason": null, "taken_over_by": null, "satisfaction": null },
  "messages": [ ...同4.2... ],
  "agent_runs": [{
    "id": "uuid", "agent_name": "triage", "graph_node": "classify",
    "provider_name": "zhipu", "model_name": "glm-4-flash",
    "status": "success", "attempt": 1, "latency_ms": 320,
    "prompt_tokens": 180, "completion_tokens": 40, "cost": 0.0001,
    "input": { "current_message": "我要退款" },
    "output": { "intents": ["refund"], "sentiment": 2.1, "urgency": "high" },
    "created_at": "..."
  }],
  "pending_approvals": [{ "id": "uuid", "risk_level": "medium", "summary": "退款 ¥299" }],
  "notes": [{ "id": "uuid", "operator": "管理员", "content": "...", "created_at": "..." }]
}
```

### POST /console/sessions/{id}/takeover — 强制接管转人工
```json
// 200  { "session": { "id": "uuid", "status": "escalated", "taken_over_by": { "id": "uuid", "display_name": "管理员" } } }
```

### POST /console/sessions/{id}/notes — 添加内部备注
```json
// Request  { "content": "用户情绪激动，已安抚" }
// 201      { "id": "uuid", "operator": "管理员", "content": "...", "created_at": "..." }
```

### POST /console/sessions/{id}/replay — 重放会话（调试/Eval）
```json
// Request  { "preset": "balanced" }        // 可选：用指定模型档位重跑
// 202      { "replay_session_id": "uuid", "stream_url": "/api/console/stream" }
```

### GET /console/sessions/{id}/export — 导出轨迹 JSON
```
// 200  Content-Type: application/json  Content-Disposition: attachment; filename=trace-{id}.json
```

---

## 8. 运营台 · 审批（P4）

### GET /console/approvals?status=pending|approved|rejected|returned|expired&page=1
```json
// 200
{ "items": [{
    "id": "uuid", "session_id": "uuid",
    "action_type": "refund",
    "action_payload": { "order_no": "1024", "amount": 299.0, "reason": "物流延迟" },
    "risk_score": 62.0,
    "risk_breakdown": { "amount": 32, "frequency": 40, "profile": 0, "sentiment": 10 },
    "risk_level": "medium", "required_approvals": 1, "granted_approvals": 0,
    "status": "pending", "timeout_at": "2026-08-14T10:00:00Z",
    "session_summary": "用户投诉无线耳机X3发货慢，要求全额退款",
    "created_at": "..."
  }], "total": 3, "page": 1, "page_size": 20 }
```

### GET /console/approvals/{id} — 详情（含完整对话摘要与轨迹链接）
```json
// 200
{ ...列表单条全部字段...,
  "conversation_digest": [ {"role": "customer", "content": "..."}, {"role": "agent", "content": "..."} ],
  "actions": [ {"operator": "审批员A", "action": "remind", "created_at": "..."} ] }
```

### POST /console/approvals/{id}/approve — 批准
```json
// Request   { "note": "已电话核实" }                  // note 可选
// Headers   Idempotency-Key: <uuid>                  // 幂等头
// 200       { "approval": { "id": "uuid", "status": "approved" },
//             "executed_action": { "id": "uuid", "status": "executed",
//               "result": { "order_no": "1024", "refund_amount": 299.0 } } }
// 409 IDEMPOTENT_CONFLICT（重复提交返回首次结果）
```

### POST /console/approvals/{id}/reject — 拒绝
```json
// Request  { "note": "不符合退款政策" }                // note 必填
// 200      { "approval": { "id": "uuid", "status": "rejected" } }
```

### POST /console/approvals/{id}/return — 驳回·要求补充信息
```json
// Request  { "note": "请补充订单号" }
// 200      { "approval": { "id": "uuid", "status": "returned" }, "session": { "status": "active" } }
```

### POST /console/approvals/{id}/remind — 催办
```json
// 200  { "ok": true, "reminded_operator": { "id": "uuid", "display_name": "审批员A" } }
```

### POST /console/approvals/batch-approve — 批量批准
```json
// Request  { "ids": ["uuid", "uuid"], "note": "批量处理" }
// 200      { "succeeded": ["uuid"], "failed": [{ "id": "uuid", "code": "ALREADY_RESOLVED" }] }
```

---

## 9. 运营台 · 知识库（P5）

### 9.1 文档

| 接口 | 说明 | 要点 |
|---|---|---|
| `GET /console/kb/documents?category=&status=&page=` | 文档列表 | 含 `current_version` 摘要 |
| `POST /console/kb/documents` | 新建文档 | body `{title, category, content}` → 创建 draft + version 1 |
| `GET /console/kb/documents/{id}` | 文档详情 | 含全部版本列表 |
| `PUT /console/kb/documents/{id}` | 编辑 | body `{title?, category?, content?}` → **产生新版本 draft**，不直接改已发布内容 |
| `POST /console/kb/documents/{id}/publish` | 发布 | body `{"effective_from": "2026-08-20"}`；同文档旧版本自动置 `retired` |
| `POST /console/kb/documents/{id}/offline` | 下线 | 旧版本可回滚 |
| `GET /console/kb/documents/{id}/versions` | 版本历史 | `[{version, effective_from, effective_to, status, created_at}]` |
| `POST /console/kb/documents/{id}/versions/{vid}/rollback` | 回滚 | 旧版本重新 active |
| `POST /console/kb/documents/import` | 批量导入 | `multipart/form-data`，字段 `files[]`（txt/md/docx） |

```json
// GET /console/kb/documents/{id} 200
{
  "id": "uuid", "title": "退货退款政策", "category": "policy", "status": "published",
  "current_version": { "version": 3, "effective_from": "2026-08-01", "status": "active" },
  "versions": [
    { "version": 3, "effective_from": "2026-08-01", "effective_to": null, "status": "active", "created_at": "..." },
    { "version": 2, "effective_from": "2026-05-01", "effective_to": "2026-07-31", "status": "retired", "created_at": "..." }
  ],
  "created_by": "operator:uuid", "created_at": "..."
}
```

### 9.2 缺口队列（已归因）

| 接口 | 说明 |
|---|---|
| `GET /console/kb/gaps?attribution=kb_gap\|retrieval_miss\|routing_error\|tool_failure&status=&page=` | 归因分类列表 |
| `POST /console/kb/gaps/{id}/generate-draft` | 对真缺口生成 KB 草稿 → `201 {draft_id}` |
| `POST /console/kb/gaps/{id}/ignore` | 忽略 |
| `POST /console/kb/gaps/{id}/reattribute` | 标记误判：body `{"correct": "retrieval_miss"}` |

```json
// GET /console/kb/gaps 200 items 单条
{ "id": "uuid", "question_digest": "耳机进水保修吗", "attribution": "kb_gap",
  "attribution_detail": { "routing_ok": true, "tool_ok": true, "retrieval_top_score": 0.31 },
  "frequency": 7, "status": "open", "created_at": "..." }
```

### 9.3 草稿审核

| 接口 | 说明 |
|---|---|
| `GET /console/kb/drafts?status=pending_review&page=` | 待审核草稿 |
| `PUT /console/kb/drafts/{id}` | 编辑草稿：`{title?, content?}` |
| `POST /console/kb/drafts/{id}/adopt` | 采纳发布 → 创建 `published` 文档（version 1，立即生效） |
| `POST /console/kb/drafts/{id}/reject` | 驳回：`{note}` 必填 |

```json
// GET /console/kb/drafts items 单条
{ "id": "uuid", "gap_record_id": "uuid", "title": "耳机进水保修政策（草稿）",
  "content": "# 保修范围\n...", "source_sessions": ["uuid", "uuid"],
  "status": "pending_review", "created_at": "..." }
```

---

## 10. 运营台 · 洞察日报（P6）

### GET /console/insights?date=2026-08-13
```json
// 200
{
  "report": {
    "report_date": "2026-08-13", "status": "generated",
    "summary": "负面会话集中爆发于物流主题…",
    "metrics": { "sessions": 96, "auto_resolution_rate": 0.71, "qc_rejection_rate": 0.18 },
    "model_used": "deepseek-chat", "generated_at": "2026-08-14T06:00:00Z"
  },
  "findings": [{
    "id": "uuid", "severity": "warning",
    "title": "「无线耳机X3」物流投诉激增 +230%",
    "detail": "近7日对比，47 条会话提及发货慢，情绪分 2.1…",
    "evidence": { "session_count": 47, "top_words": ["发货", "慢", "催"] },
    "suggested_actions": [ { "type": "kb_draft", "label": "生成物流延迟话术草稿" },
                           { "type": "ticket",   "label": "创建物流跟进工单" } ],
    "status": "new", "applied_action": null
  }]
}
```

### POST /console/insights/regenerate — 重新生成
```json
// Request  { "date": "2026-08-13" }
// 202      { "report_date": "2026-08-13", "status": "generating" }   // 完成后经 console/stream 推送 insight.ready
```

### POST /console/insights/findings/{id}/apply — 应用建议
```json
// Request  { "action_type": "kb_draft" }        // 或 "ticket"
// 201      { "draft_id": "uuid" }               // 或 { "ticket_id": "uuid" }
```

### POST /console/insights/findings/{id}/ignore — 忽略
```json
// 200  { "id": "uuid", "status": "ignored" }
```

### POST /console/insights/subscribe — 订阅日报
```json
// Request  { "channel": "email", "target": "me@example.com" }     // 或 {"channel":"webhook","target":"https://..."}
// 201      { "id": "uuid", "channel": "email", "target": "me@***.com" }
```

---

## 11. 设置 · 模型配置（P7）

### 供应商管理
| 接口 | 说明 |
|---|---|
| `GET /console/settings/providers` | 列表（密钥永远掩码） |
| `POST /console/settings/providers` | 新增：`{name, base_url, api_key}` |
| `PUT /console/settings/providers/{id}` | 编辑：`{base_url?, api_key?}`（api_key 传空=不改） |
| `DELETE /console/settings/providers/{id}` | 删除（被绑定引用时 409） |
| `POST /console/settings/providers/{id}/test` | 测试连接（发一次 1-token 请求） |

```json
// GET /console/settings/providers 200 items 单条
{ "id": 1, "name": "zhipu", "base_url": "https://open.bigmodel.cn/api/paas/v4",
  "api_key_masked": "ae13****90df", "enabled": true,
  "last_test_status": "ok", "last_tested_at": "..." }

// POST .../test 200
{ "status": "ok", "latency_ms": 450, "model": "glm-4-flash" }   // 失败: {"status":"failed","message":"401 密钥无效"}
```

### Agent 模型绑定
| 接口 | 说明 |
|---|---|
| `GET /console/settings/bindings` | 7 个 Agent 的绑定 |
| `PUT /console/settings/bindings/{agent}` | 单个修改：`{provider_id, model_name, temperature, max_tokens, fallback_chain}` |
| `POST /console/settings/bindings/apply-preset` | 一键预设：`{"preset": "economy"\|"balanced"\|"performance"}` |
| `GET /console/settings/bindings/estimate?preset=balanced` | 每千次对话预估成本 |

```json
// GET /console/settings/bindings 200
{ "items": [{
    "agent_name": "triage", "provider": { "id": 1, "name": "zhipu" },
    "model_name": "glm-4-flash", "temperature": 0.0, "max_tokens": 2048,
    "fallback_chain": [ { "provider": "deepseek", "model": "deepseek-chat" } ]
}, ...共7条... ] }

// GET .../estimate?preset=balanced 200
{ "preset": "balanced", "cost_per_1k_sessions": 2.31, "currency": "CNY" }
```

### RAG 模型
```json
// GET /console/settings/rag-models 200
{ "embedding": { "provider": "zhipu", "model": "embedding-3" },
  "reranker":  { "provider": "zhipu", "model": "reranker" } }     // reranker 可为 null
// PUT 同结构。更换 embedding 后返回 202 + 提示字段 {"reindex_required": true}
```

---

## 12. 设置 · Agent管理与提示词（P8）

### GET /console/settings/agents — Agent 列表（左栏）
```json
// 200
{ "items": [{
    "agent_name": "triage", "display_name": "分诊", "color": "#0EA5E9",
    "current_prompt": { "id": 12, "version": 3, "published_at": "..." },
    "binding": { "provider": "zhipu", "model": "glm-4-flash" },
    "versions_count": 3
}, ...共7个... ] }
```

### 提示词版本管理
| 接口 | 说明 |
|---|---|
| `GET /console/settings/agents/{agent}/prompts?status=` | 某 Agent 的版本列表 |
| `POST /console/settings/agents/{agent}/prompts` | 新建草稿版本：`{system_prompt}` |
| `GET /console/settings/prompts/{id}` | 单版本详情 |
| `PUT /console/settings/prompts/{id}` | 编辑草稿（仅 draft 可编辑，published 返回 409） |
| `POST /console/settings/prompts/{id}/publish` | 发布（新会话生效） |
| `POST /console/settings/prompts/{id}/rollback` | 回滚：`{"to_version": 2}` |
| `GET /console/settings/prompts/{id}/diff?target={id2}` | 两版本 diff |

```json
// POST /console/settings/agents/triage/prompts 201
{ "id": 15, "agent_name": "triage", "version": 4, "status": "draft",
  "system_prompt": "你是客服分诊员…{current_message}…{conversation_summary}…",
  "variables": ["{current_message}", "{conversation_summary}"], "created_at": "..." }

// GET .../diff?target=12 200
{ "from": { "id": 15, "version": 4 }, "to": { "id": 12, "version": 3 },
  "unified_diff": "--- v3\n+++ v4\n@@ -1,2 +1,3 @@\n+ 新增情绪阈值判断…" }
```

### POST /console/settings/agents/{agent}/playground — 试运行
```json
// Request
{ "prompt_version_id": 15,                       // 可选，缺省=当前发布版
  "input": { "current_message": "退款", "conversation_summary": "用户此前查过订单" } }
// 200
{ "output": { "intents": ["refund"], "sentiment": 2.0 },
  "model_used": "glm-4-flash", "latency_ms": 800,
  "prompt_tokens": 210, "completion_tokens": 35, "cost": 0.0001 }
// 注意：同步接口，前端超时设 60s；后端禁止将真实凭证/PII带入playground
```

提示词效果对比（黄金集跑分）走统一 Eval 接口，见 §16。

---

## 13. 设置 · 审批与风险规则（P9）

### GET /console/settings/risk
```json
// 200
{ "items": [
    { "rule_key": "auto_approve_limit",  "value": { "amount": 50 },  "updated_at": "...", "updated_by": "管理员" },
    { "rule_key": "queue_approve_limit", "value": { "amount": 500 }, "updated_at": "...", "updated_by": "管理员" },
    { "rule_key": "risk_weights",        "value": { "amount": 0.4, "frequency": 0.3, "profile": 0.2, "sentiment": 0.1 }, "updated_at": "..." },
    { "rule_key": "freq_aggregate_window_hours", "value": 72, "updated_at": "..." },
    { "rule_key": "approval_timeout_hours", "value": 4, "updated_at": "..." }
] }
```

### PUT /console/settings/risk — 批量更新
```json
// Request  { "auto_approve_limit": { "amount": 80 }, "risk_weights": { "amount": 0.5, "frequency": 0.2, "profile": 0.2, "sentiment": 0.1 } }
// 200      更新后的全量 items（同GET）；权重和不等于1返回 422
// 说明：对新会话生效，进行中会话用旧规则跑完（config_snapshot 机制）
```

---

## 14. 设置 · 升级硬规则（P10）

```json
// GET /console/settings/escalation 200
{ "items": [
    { "id": 1, "rule_type": "keyword",   "name": "法律/曝光关键词",
      "config": { "keywords": ["律师", "投诉到工商", "曝光"] }, "priority": 10, "enabled": true },
    { "id": 2, "rule_type": "condition", "name": "同一问题重复3次",
      "config": { "max_repeat": 3, "window_minutes": 30 }, "priority": 20, "enabled": true },
    { "id": 3, "rule_type": "condition", "name": "情绪分阈值",
      "config": { "sentiment_below": 2.0 }, "priority": 30, "enabled": true }
] }

// POST /console/settings/escalation        body: {rule_type, name, config, priority}
// PUT  /console/settings/escalation/{id}   body 同上（enabled 可单独改）
// DELETE /console/settings/escalation/{id}
// PUT  /console/settings/escalation/reorder  body: { "ids": [3, 1, 2] }   // 新优先级顺序
```

LLM 兜底开关与提示词：`PUT /console/settings/escalation` 中含特殊项 `{"id": "llm_fallback", "enabled": true}`，其提示词版本在 P8 管理（agent_name=`escalation_fallback`）。

---

## 15. 设置 · 工具权限矩阵（P11）

### GET /console/settings/permissions
```json
// 200
{
  "agents": ["triage", "supervisor", "knowledge", "order", "resolution", "qc"],
  "tools":  ["kb_search", "kb_recheck", "kb_get_doc", "query_order", "query_logistics",
             "query_account", "create_refund", "modify_order", "create_ticket", "state_ops"],
  "matrix": {
    "triage":     { "kb_search": "denied", "...": "..." },
    "resolution": { "create_refund": "required_approval", "create_ticket": "allowed", "...": "..." }
  },
  "locked": [   // 安全底线项：前端禁用交互，后端拒绝修改
    { "agent": "resolution", "tool": "create_refund", "permission": "required_approval" }
  ]
}
```

### PUT /console/settings/permissions/{agent}
```json
// Request  { "tools": { "kb_search": "allowed", "query_order": "denied" } }
// 200      更新后该 agent 的完整权限行
// 422 LOCKED_PERMISSION  尝试修改 locked 项时返回
```

---

## 16. Eval 接口

| 接口 | 说明 |
|---|---|
| `POST /console/eval/run` | 触发跑分：`{"scope": "golden_set", "preset": "balanced", "case_ids": [], "prompt_version_id": null}` → `202 {eval_batch_id}` |
| `GET /console/eval/runs?preset=&page=` | 跑分历史列表 |
| `GET /console/eval/runs/{id}` | 单次详情：状态 + 各 case 得分 + 汇总 |
| `GET /console/eval/summary` | 三档预设（economy/balanced/performance）汇总对比表（README 素材） |

```json
// GET /console/eval/runs/{id} 200
{ "id": "uuid", "preset": "balanced", "status": "finished",
  "summary": { "pass_rate": 0.86, "resolved_rate": 0.88, "hallucination_free": 0.94,
               "escalation_correct": 0.9, "total_cost": 1.24, "avg_latency_s": 6.8 },
  "cases": [ { "case_id": 1, "scenario": "injection_attack", "passed": true,
               "scores": { "resolved": true, "hallucination_free": true }, "trace_session_id": "uuid" } ] }
```

---

## 17. 管理接口（演示）

| 接口 | 认证 | 说明 |
|---|---|---|
| `GET /demo/stats` | 公开 | 落地页统计：`{"visits": 1234, "conversations": 567, "approvals": 89, "uptime_days": 12}` |
| `POST /admin/demo/reset` | JWT(admin) | 重置演示数据（重建种子订单/KB/日志），`200 {"reset": true}` |
| `POST /admin/seed/traffic` | JWT(admin) | 灌入模拟会话流量（洞察日报不冷启动）：`{"count": 50}` |

---

## 附录A：DTO 模型

**Session**
```json
{ "id": "uuid", "user": {"id": "uuid", "nickname": "张**", "user_tier": "normal"},
  "channel": "web_widget", "status": "active", "sentiment": 3.2,
  "slots": {}, "escalated_reason": null, "taken_over_by": null,
  "satisfaction": null, "message_count": 12, "last_message_at": "...", "created_at": "..." }
```

**Message**
```json
{ "id": "uuid", "session_id": "uuid", "role": "customer|agent|human_operator|system",
  "content": "...", "content_type": "text|card|system",
  "card_data": {"type": "order|refund", "...": "..."} | null,
  "agent_source": "knowledge|order|resolution|null", "status": "sent|rejected_by_qc", "created_at": "..." }
```

**AgentRun**（轨迹步骤）
```json
{ "id": "uuid", "session_id": "uuid", "agent_name": "qc", "graph_node": "qc_check",
  "provider_name": "openai", "model_name": "gpt-4o", "prompt_version_id": 8,
  "status": "success|failed|rejected|degraded", "attempt": 1,
  "latency_ms": 2100, "prompt_tokens": 800, "completion_tokens": 120, "cost": 0.009,
  "input": {}, "output": {}, "created_at": "..." }
```

**ApprovalRequest / InsightFinding / KBDocument / Prompt / Binding**：见正文对应章节示例。

## 附录B：枚举值表

| 字段 | 取值 |
|---|---|
| session.status | active / waiting_approval / escalated / closed |
| message.role | customer / agent / human_operator / system |
| message.status | sent / rejected_by_qc / revoked |
| agent_name | triage / supervisor / knowledge / order / resolution / qc / insight / escalation_fallback |
| agent_run.status | success / failed / rejected / degraded |
| approval.status | pending / approved / rejected / returned / expired |
| approval.risk_level | low / medium / high |
| kb_doc.status | draft / published / offline |
| kb_version.status | pending / active / retired |
| gap.attribution | kb_gap / retrieval_miss / routing_error / tool_failure |
| finding.severity | info / warning / critical |
| prompt.status | draft / published / retired |
| permission | allowed / required_approval / denied |
| preset | economy / balanced / performance |

## 附录C：错误码表

| code | HTTP | 场景 |
|---|---|---|
| AUTH_FAILED | 401 | 登录失败 |
| AUTH_REQUIRED | 401 | 缺少/失效 Token |
| FORBIDDEN | 403 | 角色权限不足 |
| NOT_FOUND | 404 | 资源不存在 |
| VALIDATION_ERROR | 400/422 | 参数错误（detail 指明字段） |
| SESSION_CLOSED | 409 | 向已关闭会话发消息 |
| IDEMPOTENT_CONFLICT | 409 | 幂等键冲突（返回首次结果） |
| ALREADY_RESOLVED | 409 | 审批已被处理 |
| LOCKED_PERMISSION | 422 | 修改锁定的权限项 |
| PROVIDER_IN_USE | 409 | 删除被绑定的供应商 |
| PROVIDER_TEST_FAILED | 200(业务失败) | 测试连接失败（status=failed + message） |
| RATE_LIMITED | 429 | 触发限流 |
| BUDGET_EXCEEDED | 200(SSE error事件) | 会话步数/成本预算耗尽，已降级人工 |
| REINDEX_REQUIRED | 202 | 更换 embedding 模型需重建向量索引 |

---

## 开发协作约定

1. **前端可在后端未完成时基于本文档 Mock 开发**：建议用 Apifox/Postman Mock Server 按 §2 映射表建 Mock 规则，SSE 用本地静态事件序列模拟
2. **契约变更流程**：任何字段增删先改本文档（git commit），再动代码；后端不得单方面改响应结构
3. **联调顺序建议**：认证 → 顾客端 chat + SSE（P1 先跑通，它是一切的地基）→ P3 轨迹 → P4 审批 → 其余并行
4. 所有列表接口必须先以真实分页结构交付，避免前端后期改分页逻辑
