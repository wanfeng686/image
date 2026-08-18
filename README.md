# SmartSupport · LLM 原生多 Agent 智能客服与运营系统

> 自部署开箱即用的多 Agent 客服系统：**多专家 Agent + 发送前三段式质检 · 人机协同审批 · 运营自改进闭环 · BYOM 模型自选**。

[设计文档](./DESIGN.md) · [API 契约](./API.md)

## ✨ 特性

- **多专家 Agent**（权·境·评·本四刀拆分）：Triage 分诊 / 知识库 RAG / 订单查询 / 处置执行 / 质检 QC，LangGraph 状态机编排
- **发送前三段式质检**：引用存在 → 条件覆盖（关键数字核对）→ 忠实性蕴含检查；打回重写 ≤2 次，超限降级人工
- **人机协同审批**：多维风险评分（金额 × 频次聚合 × 用户画像 × 情绪，**在代码不在 LLM**）→ 小额自动 / 中额单签 / 大额双签；幂等键三处落位，重放永不双退款
- **运营自改进闭环**：拒答缺口 → LLM 草稿 → 人工审核入库（永不自动入库）；洞察日报每日统计 + 发现
- **安全设计**：订单查询强制归属断言（防 IDOR）、30 天聚合阈值（防拆单旁路）、升级硬规则前置（关键词/VIP/情绪/追问）、转人工按钮直转铁律
- **BYOM 网关-lite**：任意 OpenAI 兼容端点即插即用，Agent 级模型绑定与温度

## 🏗️ 架构

```
顾客 Widget ──SSE 流式──► FastAPI ──► LangGraph 状态机
                                   ├─ Triage(LLM 意图+情绪+槽位, 兜底关键词)
                                   ├─ 知识库 Agent(检索→引用生成) ─► QC 三段式 ─┐(打回≤2)
                                   ├─ 订单 Agent(只读+归属断言→卡片)              ├─► 响应
                                   └─ 处置 Agent(风险评分→自动/审批/双签)          ─┘
硬规则前置闸：曝光词/VIP/情绪/追问 → 直转人工（不进状态机）
存储：PostgreSQL 16（26 表） · Redis 7 · DeepSeek(默认, 可换任意兼容端点)
```

工具权限矩阵（编排层硬编码，LLM 越权请求直接拒绝）：

| 工具 | 知识库 | 订单 | 处置 | QC |
|---|:-:|:-:|:-:|:-:|
| kb 检索/复核 | ✅ | – | – | ✅ |
| 订单查询 | – | ✅ | – | – |
| 退款写操作 | – | – | ⚠️ 需审批 | – |

## 🚀 快速开始

```bash
# 1. 依赖（Python 3.12）
cd backend && pip install -r requirements.txt

# 2. 基础设施（PostgreSQL 16 + Redis 7）
docker compose up -d

# 3. 配置 backend/.env（已 gitignore）
#    DATABASE_URL / LLM_BASE_URL / LLM_API_KEY / LLM_MODEL

# 4. 建表 + 种子数据（运营账号/规则/模拟电商/知识库/Eval 黄金集）
alembic upgrade head && python scripts/seed.py

# 5. 启动
uvicorn app.main:app --reload --port 8000
# 聊天 UI:  http://127.0.0.1:8000/           （已绑定演示顾客，订单 SO-0001/2/3）
# 运营台:   http://127.0.0.1:8000/console.html（admin/admin123 · approver/op123456）
# API 文档: http://127.0.0.1:8000/docs
```

## 🎬 演示剧本（双角色）

1. **标准流程**：`查订单 SO-0002` → 订单卡片 → `退货政策是什么` → 引用回答（QC 已检）
2. **风控流程**：`SO-0001 退款`（¥49 自动通过）→ `SO-0002 退款`（进审批队列）→ 打开运营台审批队列**亲手点批准** → 顾客会话实时收到通过通知；`SO-0003 退款` 需**双签两次**
3. **攻击流程**：`查订单 SO-2001`（他人订单 → 归属断言拦截）→ `我要去曝光你们`（硬规则直转人工）→ 注入话术（不执行任何资金动作）

## 🔒 安全设计与已知限制

| 威胁 | 对策（已实现） |
|---|---|
| 提示词注入 | 工具权限编排层硬编码；前端 textContent 渲染 |
| IDOR 越权查单 | 查询强制注入会话用户身份，"不属于你"与"不存在"同响应 |
| 拆单旁路（退 3×99 绕阈值） | 30 天累计聚合投影，超限直接升双签 |
| 质检共享盲区/遗漏条件/少量幻觉 | KB 版本+生效期过滤 + 确定性数字核对 + LLM 蕴含判定 |
| 审批重放双退款 | 幂等键三处落位（审批表/执行表 UNIQUE + 业务查重） |

**已知限制（诚实声明）**：运营台为零依赖静态页（React 重构在 Roadmap）；供应商 api_key 明文存库（演示项目，生产应 AES-GCM）；审批超时为惰性扫描（生产应 worker 定时任务）；Redis 已就位但 pub/sub 多端推送未接。

## 📊 Eval

黄金集 8 例（faq×2 / refund / order_query / idor_attack / refusal / escalation / injection_attack），`POST /api/admin/eval/run`（admin token）一键跑分，当前通过率 **8/8**。运行历史落 `eval_runs` 表。

## 🗺️ Roadmap

- 运营台 React 重构（Vite + TS + shadcn/ui，多端实时推送接 Redis pub/sub）
- Qdrant 向量检索 + 查询改写 + 重排
- 模型网关完整版（降级链/限流/成本记账）、worker 容器（APScheduler 定时任务）
- 归因链四类分流（当前简化为 kb_gap 单类）、渠道适配器（微信/抖店 webhook）

## 📄 设计文档

完整设计（29 表 DDL、7 Agent 设定卡、安全自审 19 条、里程碑）见 [DESIGN.md](./DESIGN.md)，接口契约见 [API.md](./API.md)。
