from typing import Any

from httpx import AsyncClient

from saltbox_gateway.config import SETTINGS, logger
from saltbox_gateway.utils.httpx_client import HttpxClientSingletoneFactory
from saltbox_gateway.utils.rego import ast, sql
from saltbox_gateway.utils.rego.mongo_visitor import MongoQueryVisitor
from saltbox_gateway.utils.rego.sql_visitor import SQLQueryVisitor
from saltbox_sdk.discovery_client.schemas import OPAQueryFilterFormat

type Decision = dict[str, Any]


class OPACheckPolicyException(Exception):
    """Exception raised when OPA check policy fails."""

    pass


class OPACompileException(Exception):
    """Exception raised when OPA compile fails."""

    pass


class AsyncOpaClient:
    """Async client for OPA."""

    def __init__(
        self,
        url: str | None = None,
        host: str | None = None,
        port: int | None = None,
        version: str = 'v1',
        headers: dict | None = None,
        timeout: float = 1,
        retries: int = 5,
        token: str | None = None,
        client: AsyncClient | None = None,
        # *,
        # verify_ssl: bool = False,
        # cert: str | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.version = version
        # self.verify_ssl = verify_ssl
        # self.cert = cert
        self.headers = headers or {}
        self.timeout = timeout
        self.retries = retries
        self.token = token
        if client is not None:
            self._client = client
            self._is_tmp_client = False
        else:
            self._client = AsyncClient()
            self._is_tmp_client = True
        self.base_url = f'{url}/{self.version}'

    async def check_policy(self, package: str, input: dict) -> Decision:
        url = f'{self.base_url}/data/{package}'
        data = {
            'input': input,
        }
        logger.info('OPA check policy request data: %s', data)
        logger.debug('OPA check policy request url: %s', url)
        response = await self._client.post(url, json=data, timeout=self.timeout)
        logger.debug('OPA check policy response: %s', response.content)
        if not response.is_success:
            msg = f'OPA check policy request failed: {response.status_code} {response.text}'
            raise OPACheckPolicyException(msg)
        result = response.json().get('result', {})
        if not isinstance(result, dict):
            msg = f'Invalid OPA response: {result}'
            raise OPACheckPolicyException(msg)
        if 'allow' not in result:
            msg = f'OPA response does not contain "allow" field: {result}'
            raise OPACheckPolicyException(msg)
        if not isinstance(result['allow'], bool):
            msg = f'OPA response "allow" field is not a boolean: {result}'
            raise OPACheckPolicyException(msg)
        logger.debug('OPA check policy result: %s', result)
        return result

    async def compile(
        self,
        package: str,
        input: dict,
        unknowns: list[str],
        query_filter_format: OPAQueryFilterFormat | None = OPAQueryFilterFormat.MONGO,
        partial_query: str = 'allow == true',
    ) -> dict:
        url = f'{self.base_url}/compile'
        data = {
            'query': f'data.{package}.{partial_query}',
            'input': input,
            'unknowns': ['data.' + u for u in unknowns],
        }

        logger.info('OPA compile request data: %s', data)
        logger.debug('OPA compile request url: %s', url)

        response = await self._client.post(url, json=data, timeout=self.timeout)
        logger.debug('OPA compile response: %s', response.content)
        if not response.is_success:
            msg = f'OPA compile request failed: {response.status_code} {response.text}'
            raise OPACompileException(msg)

        queries: list = response.json().get('result', {}).get('queries', [])

        if len(queries) == 0:
            return {'result': False, 'queries': None}
        if any(len(x) == 0 for x in queries):
            return {'result': True, 'queries': None}

        query_set = ast.QuerySet.from_data(queries)

        logger.debug('AST rego: %s', query_set)

        if query_filter_format == OPAQueryFilterFormat.MONGO:
            return await self._compile_to_mongo(query_set)
        if query_filter_format == OPAQueryFilterFormat.SQL:
            return await self._compile_to_sql(query_set)

        msg = f'Unsupported query filter format: {query_filter_format}'
        raise ValueError(msg)

    async def _compile_to_mongo(self, query_set: ast.QuerySet) -> dict:
        query_set.preprocess()
        visitor = MongoQueryVisitor()
        query = visitor.visit(query_set)
        logger.debug('Mongo query: %s', query)

        return {'result': True, 'query': query}

    async def _compile_to_sql(self, query_set: ast.QuerySet) -> dict:
        """Compile a query to SQL."""
        sql_visitor = SQLQueryVisitor(from_table='collections')
        clauses = sql_visitor.visit(query_set)
        logger.debug('SQL clauses: %s', clauses)
        query = sql.build_sql_query(select='collections.*', from_table='collections', clauses=clauses)
        logger.debug('SQL query: %s', query)

        return {'result': True, 'query': query}


def get_opa_client() -> AsyncOpaClient:
    """Get an instance of the OPA client."""
    httpx_client = HttpxClientSingletoneFactory.get_instance()
    return AsyncOpaClient(url=SETTINGS.opa_url, client=httpx_client)
