# SmartSupport 公网部署手册

> 适用形态：一台云服务器（2C4G 起步即可）+ 一个域名。目标：别人通过
> `https://你的域名` 访问落地页、注册商户、拿到嵌入代码和 API 密钥。

## 0. 准备清单

| 项 | 要求 | 说明 |
|---|---|---|
| 服务器 | 2核4G 起，Debian/Ubuntu | 阿里云/腾讯云轻量均可在 ~40-100元/月档位 |
| 域名 | 任意注册商 | 国内服务器需备案（见 §5）；海外服务器免备案 |
| DNS | A 记录 | `your-domain.com` → 服务器公网 IP |

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
SECRET_KEY=用下面命令生成                          # 必填！token 签名
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

## 4. 验收

```bash
curl https://你的域名/api/health          # {"status":"ok",...}
```

浏览器打开 `https://你的域名`：
1. 落地页正常，点「免费注册」创建一个测试商户
2. 门户里复制嵌入代码，本地写个 HTML 试嵌入，浮窗能聊天
3. `https://你的域名/docs` API 文档可访问

## 5. 常见问题

- **证书签发失败**：80/443 端口没放行（云厂商安全组），或 DNS 未生效（`dig your-domain.com` 核对 IP）。
- **国内备案**：域名解析到境内服务器必须 ICP 备案（个人备案约 2-3 周）；不想备案就用香港/海外节点，但境内访问速度略慢。
- **改了 compose 环境变量**：`docker compose -f docker-compose.prod.yaml up -d` 重建即可，数据在 `pg_data` 卷里不受影响。
- **商户嵌入代码里的 {ORIGIN}**：门户展示时已自动替换为当前访问的域名。
- **数据库备份**：`docker exec smart-support-postgres pg_dump -U smartbot smart_support > backup_$(date +%F).sql`

## 6. 安全检查单（上线前过一遍）

- [ ] `SECRET_KEY` 已设置（32 字节随机）
- [ ] `POSTGRES_PASSWORD` 已改强密码
- [ ] `backend/.env` 权限 600，且不在 git 里（`.gitignore` 已覆盖）
- [ ] 演示商户演示数据不影响真实商户（或删掉 seed 步骤里的演示租户）
- [ ] `/api/admin/demo/reset` 是危险接口：真实运营环境应在 main.py 里加环境开关禁用
- [ ] 各商户已在门户配置 Origin 白名单（空 = 宽松模式）
