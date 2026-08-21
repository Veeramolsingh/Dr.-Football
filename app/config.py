from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg2://scout:scout_dev_password@localhost:5433/football_scout"
    groq_api_key: str = ""

    # Two models on purpose. The SQL step wants precision and clean structured
    # output; the report step wants voice. gpt-oss-120b is excellent at the
    # former and near-immune to persona instructions (verified: it returns the
    # same terse list with the persona prompt alone, at temperature 0.4 and
    # 0.8). Qwen follows the persona properly, so it writes the prose.
    groq_sql_model: str = "openai/gpt-oss-120b"
    groq_report_model: str = "qwen/qwen3.6-27b"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
