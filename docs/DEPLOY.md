# SmartSupport 公网部署手册

> 适用形态：一台云服务器（2C4G 起步即可）+ 一个域名。目标：商家通过
> `https://你的域名` 邮箱注册、连接拼多多店铺（官方 API / RPA 托管），AI 客服自动接待买家。

## 0. 准备清单

| 项 | 要求 | 说明 |
|---|---|---|
| 服务器 | 2核4G 起，Debian/Ubuntu | 阿里云/腾讯云轻量均可在 ~40-100元/月档位 |
| 域名 | 任意注册商 | 国内服务器需备案（见 §5）；海外服务器免备案 |
| DNS | A 记录 | `your-domain.com` → 服务器公网 IP |
| SMTP 邮箱 | 一个发信账号 | 注册验证码用（如 QQ/企业邮箱 SMTP 授权码） |

## 1. 服务器初始化

```bash
ssh root@你的服务器IP
apt update && apt install -y docker.io docker-compose-plugin git

#（可选但推荐）普通用户跑 docker
# useradd -m deploy && usermod -aG docker deploy
```

## 2. 拉代码 + 配环境

```bash
git clone https://github.com/wanfeng686/image.git smart-support
cd smart-support

cp backend/.env.example backend/.env
vi backend/.env   # 填三项：
```

```ini
LLM_API_KEY=sk-你的DeepSeek或其他OpenAI兼容key   # 平台默认模型
SECRET_KEY=用下面命令生成                          # 必填！token 签名 + 渠道/模型密钥 AES-GCM 加密
SMTP_HOST=smtp.qq.com                              # 注册验证码发信（必配！）
SMTP_USER=you@qq.com
SMTP_PASS=你的SMTP授权码
SMTP_PORT=465
MAIL_DEV_MODE=false                                # 必须关闭！开着时验证码会随接口返回
# DATABASE_URL 不用改（compose 会注入容器网络地址）
```

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"   # 生成 SECRET_KEY
```

生产数据库密码（默认 smartbot_dev，务必改）：

```bash
export POSTGRES_PASSWORD=换成强密码
```

## 3. 启动

```bash
cd deploy
sed -i 's/your-domain.com/你的真实域名/' Caddyfile
docker compose -f docker-compose.prod.yaml up -d --build
```

首次启动会：建库 → 起后端 → Caddy 自动向 Let's Encrypt 申请 HTTPS 证书（需 DNS 已生效）。

初始化种子（平台管理员 + 演示商城租户，只需一次）：

```bash
docker exec smart-support-backend python - <<'EOF'
import subprocess
subprocess.run(["alembic", "upgrade", "head"], check=True)
subprocess.run(["python", "scripts/seed.py"], check=True)
EOF
```

## 4. RPA Worker（浏览器托管通道，可选）

商户走 RPA 模式接入时需要常驻 worker 进程（Playwright 控制浏览器登录商家后台收发消息）：

```bash
# 服务器上直接跑（需要 python + playwright，chromium 无头）
cd smart-support/backend
pip install -r requirements.txt && playwright install chromium

# 用 systemd 常驻（推荐）：/etc/systemd/system/ss-worker.service
# [Service]
# WorkingDirectory=/opt/smart-support/backend
# ExecStart=/usr/bin/python3 scripts/channel_worker.py --poll 5
# Restart=always
systemctl enable --now ss-worker

# 或手动验证：python scripts/channel_worker.py --once
```

⚠️ **RPA 合规提示**：RPA 通过浏览器自动化操作商家后台，**不符合平台官方服务协议**，
商家侧存在限流/封店风险。平台已在向导中强制风险知情勾选并存档同意时间；
对外运营前请评估相关法务/平台政策风险，并考虑优先引导商户走官方 API。

## 5. 验收

```bash
curl https://你的域名/api/health          # {"status":"ok",...}
```

浏览器打开 `https://你的域名`：
1. 落地页正常，点「免费注册」用邮箱收验证码创建商户
2. 向导选拼多多 → RPA 模式（或官方 API）→ 连接状态变「已连接」
3. RPA 演示：本地打开 `https://你的域名/simulator/` 是内置模拟后台（仅演示/测试用）
4. `https://你的域名/docs` API 文档可访问

## 6. 常见问题

- **证书签发失败**：80/443 端口没放行（云厂商安全组），或 DNS 未生效（`dig your-domain.com` 核对 IP）。
- **国内备案**：域名解析到境内服务器必须 ICP 备案（个人备案约 2-3 周）；不想备案就用香港/海外节点，但境内访问速度略慢。
- **改了 compose 环境变量**：`docker compose -f docker-compose.prod.yaml up -d` 重建即可，数据在 `pg_data` 卷里不受影响。
- **验证码收不到**：核对 SMTP_HOST/USER/PASS（QQ 邮箱用「授权码」不是登录密码）；MAIL_DEV_MODE 必须为 false。
- **RPA 连接一直 error**：看连接卡片上的 last_error；`python scripts/channel_worker.py --once` 单周期复现；真实平台需先联调 selectors.py。
- **数据库备份**：`docker exec smart-support-postgres pg_dump -U smartbot smart_support > backup_$(date +%F).sql`

## 7. 安全检查单（上线前过一遍）

- [ ] `SECRET_KEY` 已设置（32 字节随机；同时是渠道凭据与**商户模型 api_key** 的加密密钥，**换密钥=已存密文全部作废**）
- [ ] BYOK 语义已知晓：商户必须自带模型服务（未配置则 AI 不回复，409 闸门），平台 `.env` 的 LLM_* 仅服务演示租户种子与平台内部工具
- [ ] `POSTGRES_PASSWORD` 已改强密码
- [ ] SMTP 已配置且 `MAIL_DEV_MODE=false`（开着=验证码明文返回给任何请求方）
- [ ] `backend/.env` 权限 600，且不在 git 里（`.gitignore` 已覆盖）
- [ ] 演示商户演示数据不影响真实商户（或删掉 seed 步骤里的演示租户）
- [ ] `/api/admin/demo/reset` 是危险接口：真实运营环境应在 main.py 里加环境开关禁用
- [ ] RPA worker 的合规风险已知悉（§4）；模拟后台 `/simulator/` 仅演示用，可考虑生产环境移除
- [ ] RPA 浏览器 profile 目录（backend/rpa_profiles/）含登录态，权限等同凭据保管
