# SmartSupport · 电商 AI 客服平台（SaaS）

> 商家用**邮箱注册** → 选择自己的**电商平台店铺**（拼多多已支持，淘宝/抖店/京东等即将开放）→
> 有官方 API 填凭据，没有就**浏览器托管（RPA）** → 买家咨询自动进入**多 Agent 智能客服引擎**：
> 会查订单、能办退款（带人工审批）、每句回答发出前过三段式质检。

[设计文档](./DESIGN.md) · [API 契约](./API.md) · [部署手册](./docs/DEPLOY.md)

## ✨ 三步接入

```
1️⃣ 邮箱注册                2️⃣ 连接店铺                      3️⃣ AI 自动接待
   验证码 30 秒开户       拼多多：官方API凭据 / RPA店铺账密      买家在平台聊天窗发问
                          （淘宝/抖店/京东…即将支持）            查订单 · 答政策 · 办退款
```

**平台支持矩阵**：

| 平台 | 官方 API | 浏览器托管 RPA |
|---|:-:|:-:|
| 拼多多 | ✅ | ✅ |
| 淘宝/天猫 · 抖音小店 · 京东 · 快手小店 · 小红书 · 微信小店 | 🚧 即将支持 | 🚧 即将支持 |

**两种接入方式**：

- **官方 API（推荐）**：拼多多开放平台应用的 client_id/secret（AES-256-GCM 加密存储），
  商家授权后补填 access_token。合规稳定。
- **浏览器托管（RPA）**：商家提供店铺账号，平台用 Playwright 托管浏览器登录商家后台收发消息。
  ⚠️ **非官方通道，不符合平台服务协议，存在限流/封店风险** —— 创建时强制风险知情勾选，
  凭据加密存储，本地可用内置「模拟拼多多后台」完整演示与测试。

**自带模型（BYOK，必填）**：商户注册后必须在向导第 1 步配置自己的大模型服务
（任意 OpenAI 兼容端点：DeepSeek / 通义 / 智谱 / 本地 Ollama），api_key AES-256-GCM 加密存储；
**未配置的商户 AI 客服不回复任何消息**（对话入口 409 闸门）。平台不代付模型费用，
只在运营台/门户提供默认「客服人设提示词模板」，商户可自定义改写或一键还原。

另有 **sk_ 开放 API**：商户后端推送商品/订单（upsert）、创建会话、发消息拿完整回复。

## 🤖 引擎特性（每个商户独立拥有）

- **多专家 Agent**：Triage 分诊 / 知识库 RAG / 订单查询 / 处置执行 / 质检 QC，LangGraph 状态机编排
- **发送前三段式质检**：引用存在 → 条件覆盖（关键数字核对）→ 忠实性蕴含检查；打回重写 ≤2 次，超限降级人工
- **人机协同审批**：多维风险评分（金额 × 频次聚合 × 用户画像 × 情绪，**在代码不在 LLM**）→ 小额自动 / 中额单签 / 大额双签；幂等键三处落位，重放永不双退款
- **运营自改进闭环**：拒答缺口 → LLM 草稿 → 人工审核入库（永不自动入库）；每日洞察日报
- **BYOK 强制**：每个商户自带模型服务（门户「AI 模型与提示词」一站式配置，运营台可按 Agent 细分绑定），密钥密文落库
- **提示词模板**：客服人设系统提示词平台供默认模板、商户可改可还原（分诊/质检等内部提示词不开放，防破坏路由与 JSON 解析）

## 🏗️ 架构

```
拼多多买家 ──平台聊天窗──► 商家后台（官方API / RPA托管浏览器）─┐
                                                              ├─► 渠道适配器 ─► 渠道桥 ─► LangGraph 状态机
商户后端 ───sk_密钥──► /api/v1/*（推数据 · API会话）           │   (统一 InboundMessage/OutboundReply)
                                                              │   会话按 (租户, 平台:会话ID) 映射复用
商户运营 ──浏览器──► /portal.html（邮箱注册/连接向导/数据）      │   卡片降级为纯文本回发
                    /console.html（审批/知识库/洞察，租户隔离）  ┘
平台管理员 ─────────► /api/platform/tenants（跨租户）

RPA Worker（scripts/channel_worker.py，独立进程）：
  轮询 connected 的 RPA 连接 → Playwright 持久化 profile 登录 → 读新消息 → 引擎 → 回复填回
密钥体系：sk_(商户后端) · Bearer token(操作员/管理员) · 渠道凭据(AES-GCM 密文) · pk_(内部演示页)
存储：PostgreSQL（30 表，租户外键贯穿） · Redis 7
```

工具权限矩阵（编排层硬编码，LLM 越权请求直接拒绝）：

| 工具 | 知识库 | 订单 | 处置 | QC |
|---|:-:|:-:|:-:|:-:|
| kb 检索/复核 | ✅ | – | – | ✅ |
| 订单查询 | – | ✅ | – | – |
| 退款写操作 | – | – | ⚠️ 需审批 | – |

## 🚀 本地跑起来

```bash
# 1. 依赖（Python 3.12）
cd backend && pip install -r requirements.txt
playwright install chromium          # RPA 托管浏览器用（~115MB）

# 2. 基础设施（PostgreSQL 16 + Redis 7）
docker compose up -d

# 3. 配置 backend/.env（参考 .env.example：DATABASE_URL / LLM_* / SECRET_KEY / SMTP_*）

# 4. 建表 + 种子（演示商城租户 + 平台账号 + 订单/知识库/Eval 黄金集）
alembic upgrade head && python scripts/seed.py

# 5. 启动 API
uvicorn app.main:app --reload --port 8000

# 6. RPA Worker（另开一个终端；不跑则只有官方API通道）
python scripts/channel_worker.py --headed       # 有头模式看得到浏览器操作；--once 单周期
```

| 入口 | 地址 | 账号 |
|---|---|---|
| 落地页（注册/体验） | http://127.0.0.1:8000/ | – |
| 商户门户（连接向导/数据/设置） | http://127.0.0.1:8000/portal.html | 自己邮箱注册，或 `shop / shop123` |
| 运营台（审批/知识库/洞察） | http://127.0.0.1:8000/console.html | 商户 `shop/shop123` · 平台 `admin/admin123` |
| 模拟拼多多后台（RPA 演示） | http://127.0.0.1:8000/simulator/ | 任意账密 |
| 演示商城顾客视角 | http://127.0.0.1:8000/demo.html | – |
| API 文档 | http://127.0.0.1:8000/docs | – |

公网部署（Caddy 自动 HTTPS + 生产 compose）：见 [docs/DEPLOY.md](./docs/DEPLOY.md)。

## 🎬 演示剧本

1. **当顾客**：demo.html 里 `查订单 SO-0002` → 订单卡片 → `退货政策是什么` → 引用回答（QC 已检）
2. **当商户**：portal.html 邮箱注册 → 向导选拼多多 → RPA 模式（勾风险同意）→ 填店铺账密 → 连接「已连接」
3. **看 RPA 自动接待**：`python scripts/channel_worker.py --headed` → 内置模拟后台弹出 →
   机器人买家「帮我查一下订单 S-7701 到哪了」→ AI 自动回复订单信息 → 追问退货 → 走完整退款审批流
4. **当运营**：console.html 审批队列**亲手批准**退款 → 会话实时收到通知；知识库改版本 → 发布 → 检索立即生效；洞察日报重新生成
5. **攻击演示**：`查订单 SO-2001`（他人订单 → 归属断言拦截）→ `我要去曝光你们`（硬规则直转人工）→ 注入话术（不执行任何资金动作）

## 🔒 安全设计与已知限制

| 威胁 | 对策（已实现） |
|---|---|
| 提示词注入 | 工具权限编排层硬编码；前端 textContent 渲染 |
| IDOR 越权查单 | 查询强制注入会话用户身份，"不属于你"与"不存在"同响应 |
| 租户数据越界 | 全链路 tenant_id 过滤；跨租户资源访问返回 404（与不存在同响应） |
| 渠道凭据泄露 | AES-256-GCM 加密落库（SECRET_KEY 派生密钥），接口只回脱敏形态 |
| 拆单旁路（退 3×99 绕阈值） | 30 天累计聚合投影，超限直接升双签 |
| 质检共享盲区/遗漏条件/少量幻觉 | KB 版本+生效期过滤 + 确定性数字核对 + LLM 蕴含判定 |
| 审批重放双退款 | 幂等键三处落位（审批表/执行表 UNIQUE + 业务查重） |
| 注册轰炸/验证码暴力 | 邮箱验证码 60s 冷却 + 哈希落库 + 10 分钟过期 + 尝试次数上限 |
| RPA 误用 | 创建强制风险知情勾选（consent_at 留档）；凭据仅密文存储 |

**已知限制（诚实声明）**：
- **RPA 真实平台联调未完成**：真实拼多多/淘宝后台选择器是骨架（`rpa/selectors.py` 的 PDD_REAL 待核对），
  需要真实商家账号后逐项联调；本地以内置模拟后台验证全链路
- **拼多多官方 API**：签名/调用/店铺信息测试已实现，消息收发接口（pdd.im.*）的 type 名与参数需真实凭据联调核对；
  完整功能需商家 OAuth 授权 access_token
- 门户/运营台为零依赖静态页（React 重构在 Roadmap）；ModelProvider api_key 与租户 sk_ 仍明文存库（渠道凭据已加密，这两项生产应跟进）
- 未配 SMTP 时验证码走 mail_dev_mode 回退（打印日志+响应返回），**生产必须配 SMTP 并关闭该模式**
- 审批超时为惰性扫描（生产应 worker 定时任务）；Redis 已就位但 pub/sub 多端推送未接
- 无计费/配额（plan 字段已预留）
- `/api/admin/demo/reset` 会清空全部租户动态数据，真实运营需禁用（见 DEPLOY.md 检查单）

## 📊 Eval

黄金集 8 例（faq×2 / refund / order_query / idor_attack / refusal / escalation / injection_attack），
`POST /api/admin/eval/run`（平台 admin token）一键跑分，当前通过率 **8/8**，历史落 `eval_runs` 表。

## 🧪 测试

```bash
python scripts/test_c1_email.py       # 邮箱注册/验证码/登录 15 例
python scripts/test_c2_channels.py    # 平台目录/连接CRUD/加密/RPA同意门/Widget移除 25 例
python scripts/test_c3_bridge.py      # 渠道桥/会话映射/卡片降级 13 例
python scripts/test_c4_rpa.py         # RPA 端到端闭环（headless）12 例
python scripts/test_c6_ai.py          # BYOK 闸门/密钥加密/提示词模板驱动 LLM 19 例
python scripts/test_s1_isolation.py   # 租户隔离 10 例
python scripts/test_s2.py             # 门户 + 开放 API 25 例
python scripts/test_w2.py             # 退款三路/幂等/轨迹 15 例（前置 reset+seed）
python scripts/test_w3.py             # 质检回环/升级/运营台 23 例
python scripts/test_w4.py             # KB版本/洞察/Eval/设置 18 例
```

## 🗺️ Roadmap

- 淘宝/抖店/京东/快手/小红书/微信小店适配（官方 API + RPA 选择器联调）
- 拼多多消息接口真实联调（OAuth 授权流 + pdd.im.* 参数核对）
- RPA 加固：滑块/验证码处理、异地登录风控对策、会话保活
- sk_ 哈希存储、计费与配额、React 运营台重构、Redis pub/sub 实时推送
- Qdrant 向量检索 + 查询改写 + 重排；worker 容器化（审批超时/日报定时任务）
