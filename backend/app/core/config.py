from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = ""
    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"

    model_config = {"env_file": ".env"}


settings = Settings()