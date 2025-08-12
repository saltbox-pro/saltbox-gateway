import httpx

from saltbox_gateway.config import SETTINGS, logger


class HttpxClientSingletoneFactory:
    _instance: httpx.AsyncClient | None = None

    @classmethod
    def get_instance(cls) -> httpx.AsyncClient:
        """Get a singleton instance of httpx.AsyncClient."""
        if cls._instance is None:
            auth = None
            if SETTINGS.basic_auth_username != '' and SETTINGS.basic_auth_password != '':
                auth = httpx.BasicAuth(SETTINGS.basic_auth_username, SETTINGS.basic_auth_password)
            timeout = httpx.Timeout(
                connect=SETTINGS.proxy_connect_timeout,
                read=SETTINGS.proxy_read_timeout,
                write=SETTINGS.proxy_write_timeout,
                pool=SETTINGS.proxy_pool_timeout,
            )
            limits = httpx.Limits(
                max_connections=SETTINGS.httpx_max_connections,
                max_keepalive_connections=SETTINGS.httpx_max_keepalive,
                keepalive_expiry=SETTINGS.httpx_keepalive_expiry,
            )
            cls._instance = httpx.AsyncClient(auth=auth, timeout=timeout, limits=limits)
            logger.debug('HTTPX AsyncClient initialized.')
        else:
            logger.debug('Using existing HTTPX AsyncClient instance.')
        return cls._instance
