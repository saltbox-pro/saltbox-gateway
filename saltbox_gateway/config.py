import logging.config
import os
from pathlib import Path

from faststream.rabbit import RabbitBroker
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from saltbox_sdk.config.rabbitmq_config import RabbitSettings
from saltbox_sdk.config.redis_config import RedisSettings

APP_NAME = 'Salt.Box Gateway'
APP_DESC = 'Salt.Box Gateway and Service Discovery API'
ENV_FILE = Path(os.environ.get('SALTBOX_ENV_FILE', '.env'))


class AppSettings(BaseSettings):
    log_level: str = 'INFO'
    server_outer_socket: str = 'localhost'
    server_ws_scheme: str = 'ws'
    server_scheme: str = 'http'
    static_proxy_prefix: str = '/static'
    basic_auth_username: str = ''
    basic_auth_password: str = ''
    origins: list[str] = Field(['*'], description='CORS allowed resources')
    opa_url: str = ''
    official_modules: list[str] = [
        'core',
        'processing',
        'metric',
        'scheduler',
        'inventory',
        'migration',
        'audit',
        'client-toolkit',
    ]
    service_registration_ttl: int = 3600
    proxy_request_timeout: int = 10
    # granular HTTPX timeouts
    proxy_connect_timeout: float = 3.0
    proxy_read_timeout: float = 10.0
    proxy_write_timeout: float = 10.0
    proxy_pool_timeout: float = 5.0
    # HTTPX pool limits
    httpx_max_connections: int = 200
    httpx_max_keepalive: int = 50
    httpx_keepalive_expiry: float = 60.0
    # Simple retry policy for idempotent requests
    proxy_retries: int = 2
    proxy_retry_backoff_base: float = 0.1  # seconds, exponential backoff
    proxy_retry_on_status: list[int] = Field(default_factory=lambda: [502, 503, 504])
    proxy_retry_idempotent_methods: list[str] = Field(default_factory=lambda: ['GET', 'HEAD', 'OPTIONS'])
    rabbit_mq_reconnect_interval: float = 5.0  # TODO (a.karmanov): SBX-170 Decide to move to SDK rabbit_config
    health_check_interval: int = 15
    health_check_timeout: int = 3

    model_config = SettingsConfigDict(env_file=ENV_FILE, extra='ignore')


class Settings(BaseSettings):
    app: AppSettings = Field(default_factory=AppSettings)
    rabbitmq: RabbitSettings = Field(default_factory=RabbitSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)


SETTINGS = Settings()

# TODO (a.karmanov): SBX-170 Decide to init in SDK
broker = RabbitBroker(
    url=SETTINGS.rabbitmq.url,
    fail_fast=False,  # Keep trying to connect
    reconnect_interval=SETTINGS.app.rabbit_mq_reconnect_interval,
)


def get_broker() -> RabbitBroker:
    return broker


class LogConfig(BaseModel):
    LOG_FORMAT: str = '%(levelprefix)s [%(filename)s:%(lineno)d] %(message)s'
    LOG_LEVEL: str = SETTINGS.app.log_level.upper()

    version: int = 1
    disable_existing_loggers: bool = False
    formatters: dict = {
        'default': {
            '()': 'uvicorn.logging.DefaultFormatter',
            'datefmt': '%Y-%m-%d %H:%M:%S',
            'fmt': LOG_FORMAT,
        },
    }
    handlers: dict = {
        'default': {
            'class': 'logging.StreamHandler',
            'formatter': 'default',
            'stream': 'ext://sys.stderr',
        },
    }
    loggers: dict = {
        'saltbox_gateway': {
            'handlers': ['default'],
            'level': LOG_LEVEL,
            'propagate': False,
        },
    }


LOG_CONFIG = LogConfig()

logging.config.dictConfig(LOG_CONFIG.model_dump())

logger = logging.getLogger('saltbox_gateway')
