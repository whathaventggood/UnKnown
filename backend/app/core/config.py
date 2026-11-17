from pathlib import Path
from typing import Literal
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[3]

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(ROOT / '.env'), extra='ignore')
    database_url: str = f'sqlite:///{ROOT / "data/unknown.db"}'
    cookie_secure: bool = False
    cookie_samesite: Literal['lax','strict','none'] = 'lax'
    public_origin: str | None = None
    cors_origins: list[str] = ['http://127.0.0.1:5173', 'http://localhost:5173', 'http://127.0.0.1:5183']
    default_timezone: str = 'Asia/Shanghai'
    semantic_similarity: bool = True
    llm_api_key: str = ''
    llm_base_url: str = 'https://api.deepseek.com'
    llm_model: str = 'deepseek-flash'
    llm_trust_env: bool = False
    llm_json_mode: bool = False  # opt in for provider/model that documents support
    llm_timeout_seconds: float = Field(40, ge=1, le=120)
    llm_retries: int = Field(1, ge=0, le=2)
    llm_max_output_tokens: int = Field(1800, ge=100, le=8000)
    llm_context_chars: int = Field(14000, ge=1000, le=40000)
    llm_user_daily_requests: int = Field(20, ge=0)
    llm_global_daily_requests: int = Field(100, ge=0)
    llm_user_daily_tokens: int = Field(50000, ge=0)
    llm_global_daily_tokens: int = Field(250000, ge=0)
    openalex_api_key: str = ''
    ingestion_user_agent: str = 'UnKnown/0.1 (self-hosted educational explorer)'

    @field_validator('cors_origins')
    @classmethod
    def exact_origins(cls, values):
        from urllib.parse import urlsplit
        for value in values:
            p = urlsplit(value)
            if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password or p.path or p.query or p.fragment or '*' in value:
                raise ValueError('CORS_ORIGINS requires exact HTTP(S) origins without paths or wildcards')
        return values

    @field_validator('public_origin')
    @classmethod
    def exact_public_origin(cls, value):
        if value is not None:
            cls.exact_origins([value])
        return value

    @model_validator(mode='after')
    def secure_cross_site_cookie(self):
        if self.cookie_samesite == 'none' and not self.cookie_secure:
            raise ValueError('SameSite=None requires COOKIE_SECURE=true (HTTPS)')
        return self

    @field_validator('default_timezone')
    @classmethod
    def valid_zone(cls, value):
        ZoneInfo(value)
        return value

    @field_validator('llm_base_url')
    @classmethod
    def valid_url(cls, value):
        from urllib.parse import urlsplit
        p = urlsplit(value)
        if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password or p.query or p.fragment:
            raise ValueError('LLM_BASE_URL must be an HTTP(S) server URL without credentials/query')
        return value.rstrip('/')
