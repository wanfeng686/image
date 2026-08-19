from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = ""
    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"
    # token 签名密钥：生产部署必须显式设置（python -c "import secrets; print(secrets.token_hex(32))"）
    secret_key: str = ""

    model_config = {"env_file": ".env"}


settings = Settings()
