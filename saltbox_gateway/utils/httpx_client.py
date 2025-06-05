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
            cls._instance = httpx.AsyncClient(auth=auth)
            logger.debug('HTTPX AsyncClient initialized.')
        else:
            logger.debug('Using existing HTTPX AsyncClient instance.')
        return cls._instance
