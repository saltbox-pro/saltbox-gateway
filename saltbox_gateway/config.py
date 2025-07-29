import logging.config
from typing import Any, Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_NAME = 'Salt.Box Gateway'
APP_DESC = 'Salt.Box Gateway and Service Discovery API'


class Settings(BaseSettings):
    log_level: str = 'INFO'
    server_outer_socket: str
    server_ws_scheme: str = 'ws'
    server_scheme: str = 'http'
    static_proxy_prefix: str = '/static'
    basic_auth_username: str = ''
    basic_auth_password: str = ''
    origins: list[str] = Field(['*'], description='CORS allowed resources')
    redis_ca_cert: str | None = Field(None, description='Path to file of concatenated PEM certs')
    redis_password: str | None = None
    redis_tls_verification: Literal['none', 'optional', 'required'] = 'required'
    redis_url: str = ''
    redis_username: str | None = None
    opa_url: str = ''
    official_modules: list[str] = ['core', 'processing', 'scheduler']
    service_registration_ttl: int = 3600
    proxy_request_timeout: int = 10
    health_check_interval: int = 15
    health_check_timeout: int = 3

    model_config = SettingsConfigDict(env_file='.env')

    @property
    def redis_connection_kwargs(self) -> dict[str, Any]:
        """
        Additional options for redis.*.from_url() group of methods
        """
        result = {
            'username': self.redis_username,
            'password': self.redis_password,
        }
        if self.redis_url.startswith('rediss:'):
            result |= {
                'ssl_cert_reqs': self.redis_tls_verification,
                'ssl_ca_certs': self.redis_ca_cert,
            }
        return result


SETTINGS = Settings()


class LogConfig(BaseModel):
    LOG_FORMAT: str = '%(levelprefix)s [%(filename)s:%(lineno)d] %(message)s'
    LOG_LEVEL: str = SETTINGS.log_level.upper()

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
