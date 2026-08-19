from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = ""
    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"
    # token 签名密钥：生产部署必须显式设置（python -c "import secrets; print(secrets.token_hex(32))"）
    secret_key: str = ""
    # SMTP 发信（邮箱验证码）。未配置时：mail_dev_mode=True 则验证码打日志并随响应返回（本地联调），
    # 生产必须配置真实 SMTP 并将 mail_dev_mode 置 false（见 docs/DEPLOY.md 清单）。
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_pass: str = ""
    smtp_from: str = ""          # 发件人地址，缺省用 smtp_user
    mail_dev_mode: bool = True
    # RPA 渠道目标：simulator=内置模拟后台（演示/测试），real=真实商家后台（需联调选择器）
    channel_rpa_target: str = "simulator"
    channel_sim_url: str = "http://127.0.0.1:8000/simulator/"

    model_config = {"env_file": ".env"}


settings = Settings()
