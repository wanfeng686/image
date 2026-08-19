# SmartSupport · AI 客服即服务平台（SaaS）

> 商家注册账号 → 贴一行代码，网站立刻拥有**多 Agent 智能客服**：会查订单、能办退款（带人工审批）、
> 每句回答发出前过三段式质检。**多租户隔离 · Widget 嵌入 · 开放 API · BYOM 自带模型**。

[设计文档](./DESIGN.md) · [API 契约](./API.md) · [部署手册](./docs/DEPLOY.md)

## ✨ 三步接入

```
1️⃣ 注册商户           2️⃣ 嵌入网站                          3️⃣ 导入数据
  门户 30 秒开户          <script src="…/embed.js"             POST /api/v1/orders (sk_)
 拿到 pk_/sk_ 双密钥           data-key="pk_…" async>           或门户 CSV 上传
```

- **网页 Widget**：右下角客服浮窗，品牌化（标题/欢迎语/主题色），域名白名单管控
- **开放 API**：商户后端用 sk_ 推送商品/订单（upsert）、创建会话、发消息拿完整回复
- **多租户硬隔离**：知识库 / 订单 / 规则 / 模型配置 / 会话 / 审批全部按租户切分，越权一律 404

## 🤖 引擎特性（每个商户独立拥有）

- **多专家 Agent**（权·境·评·本四刀拆分）：Triage 分诊 / 知识库 RAG / 订单查询 / 处置执行 / 质检 QC，LangGraph 状态机编排
- **发送前三段式质检**：引用存在 → 条件覆盖（关键数字核对）→ 忠实性蕴含检查；打回重写 ≤2 次，超限降级人工
- **人机协同审批**：多维风险评分（金额 × 频次聚合 × 用户画像 × 情绪，**在代码不在 LLM**）→ 小额自动 / 中额单签 / 大额双签；幂等键三处落位，重放永不双退款
- **运营自改进闭环**：拒答缺口 → LLM 草稿 → 人工审核入库（永不自动入库）；每日洞察日报
- **BYOM**：商户在运营台配任意 OpenAI 兼容端点（DeepSeek/OpenAI/智谱/Ollama），不配走平台默认

## 🏗️ 架构

```
商户网站 ──贴script──► /embed.js ──注入──► iframe(/widget/?key=pk_…) ─┐
商户后端 ──sk_密钥──► /api/v1/*（推数据 · API会话）                    ├─► FastAPI ─► LangGraph 状态机
商户运营 ──浏览器──► /portal.html + /console.html（租户隔离）         ─┘      ├─ Triage(LLM 意图+情绪+槽位, 兜底关键词)
                                                                                ├─ 知识库 Agent(检索→引用生成) ─► QC 三段式 ─┐(打回≤2)
平台管理员 ─────────► /api/platform/tenants（跨租户）                            ├─ 订单 Agent(只读+归属断言→卡片)           ├─► 响应
                                                                                └─ 处置 Agent(风险评分→自动/审批/双签)       ─┘
三层密钥：pk_(浏览器Widget) · sk_(商户后端) · Bearer token(操作员)     硬规则前置闸：曝光词/VIP/情绪/追问 → 直转人工
存储：PostgreSQL 16（27 表，租户外键贯穿） · Redis 7                     转人工按钮直转（铁律）
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

# 2. 基础设施（PostgreSQL 16 + Redis 7）
docker compose up -d

# 3. 配置 backend/.env（参考 .env.example：DATABASE_URL / LLM_* / SECRET_KEY）

# 4. 建表 + 种子（演示商城租户 + 平台账号 + 订单/知识库/Eval 黄金集）
alembic upgrade head && python scripts/seed.py

# 5. 启动
uvicorn app.main:app --reload --port 8000
```

| 入口 | 地址 | 账号 |
|---|---|---|
| 落地页（注册/体验） | http://127.0.0.1:8000/ | – |
| 商户门户（接入/数据） | http://127.0.0.1:8000/portal.html | 自己注册，或 `shop / shop123` |
| 运营台（审批/知识库/洞察） | http://127.0.0.1:8000/console.html | 商户 `shop/shop123` · 平台 `admin/admin123` |
| 演示商城顾客视角 | http://127.0.0.1:8000/demo.html | – |
| Widget 嵌入效果 | http://127.0.0.1:8000/test-merchant.html | – |
| API 文档 | http://127.0.0.1:8000/docs | – |

公网部署（Caddy 自动 HTTPS + 生产 compose）：见 [docs/DEPLOY.md](./docs/DEPLOY.md)。

## 🎬 演示剧本（双角色 → 三角色）

1. **当顾客**：demo.html 里 `查订单 SO-0002` → 订单卡片 → `退货政策是什么` → 引用回答（QC 已检）
2. **当商户**：portal.html 注册自己的店 → 复制嵌入代码 → 打开 test-merchant.html 看浮窗效果 → 数据页 CSV 导入 / API 推单
3. **当运营**：console.html 审批队列**亲手批准** `SO-0002 退款` → 顾客会话实时收到通知；`SO-0003` 需双签两次；知识库改版本 → 发布 → 检索立即生效；洞察日报重新生成
4. **攻击演示**：`查订单 SO-2001`（他人订单 → 归属断言拦截）→ `我要去曝光你们`（硬规则直转人工）→ 注入话术（不执行任何资金动作）

## 🔒 安全设计与已知限制

| 威胁 | 对策（已实现） |
|---|---|
| 提示词注入 | 工具权限编排层硬编码；前端 textContent 渲染 |
| IDOR 越权查单 | 查询强制注入会话用户身份，"不属于你"与"不存在"同响应 |
| 租户数据越界 | 全链路 tenant_id 过滤；跨租户资源访问返回 404（与不存在同响应） |
| 拆单旁路（退 3×99 绕阈值） | 30 天累计聚合投影，超限直接升双签 |
| 质检共享盲区/遗漏条件/少量幻觉 | KB 版本+生效期过滤 + 确定性数字核对 + LLM 蕴含判定 |
| 审批重放双退款 | 幂等键三处落位（审批表/执行表 UNIQUE + 业务查重） |
| 恶意站点盗嵌 Widget | pk_ 密钥 + Origin 白名单（声明式，见下方限制） |

**已知限制（诚实声明）**：
- Widget 白名单为**声明式**校验（iframe 架构下浏览器 Origin 是平台域名，靠 X-Widget-Origin 声明头），防顺手嵌入；强域名归属验证（DNS TXT）在 Roadmap
- 门户/运营台为零依赖静态页（React 重构在 Roadmap）；供应商与租户 api_key/sk_ 明文存库（演示项目，生产应 AES-GCM 加密 + 密钥哈希）
- 审批超时为惰性扫描（生产应 worker 定时任务）；Redis 已就位但 pub/sub 多端推送未接
- 无计费/配额（plan 字段已预留）；注册无邮箱验证
- `/api/admin/demo/reset` 会清空全部租户动态数据，真实运营需禁用（见 DEPLOY.md 检查单）

## 📊 Eval

黄金集 8 例（faq×2 / refund / order_query / idor_attack / refusal / escalation / injection_attack），
`POST /api/admin/eval/run`（平台 admin token）一键跑分，当前通过率 **8/8**，历史落 `eval_runs` 表。

## 🧪 测试

```bash
python scripts/test_s1_isolation.py   # 租户隔离 12 例
python scripts/test_s2.py             # 门户 + 开放 API 28 例
python scripts/test_s3.py             # Widget 链路 13 例
python scripts/test_w2.py             # 退款三路/幂等/轨迹 15 例（前置 reset+seed）
python scripts/test_w3.py             # 质检回环/升级/运营台 23 例
python scripts/test_w4.py             # KB版本/洞察/Eval/设置 18 例
```

## 🗺️ Roadmap

- 域名归属强验证（DNS TXT / meta 标签）、sk_ 哈希存储、注册邮箱验证、计费与配额
- 运营台 React 重构（Vite + TS + shadcn/ui）、Redis pub/sub 多端实时推送
- Qdrant 向量检索 + 查询改写 + 重排；模型网关完整版（降级链/限流/成本记账）
- worker 容器（APScheduler：审批超时扫描 / 洞察日报定时生成 / 30 天退款额度重算）
- 渠道适配器（微信客服/抖店 webhook）——商户"平台账号"直连

## 📄 设计文档

完整设计（表结构、7 Agent 设定卡、安全自审 19 条、里程碑）见 [DESIGN.md](./DESIGN.md)，接口契约见 [API.md](./API.md)，部署见 [docs/DEPLOY.md](./docs/DEPLOY.md)。
