from typing import Any

from httpx import AsyncClient

from saltbox_gateway.config import SETTINGS, logger
from saltbox_gateway.exceptions import OpaRequestException, OpaResponseFormatException
from saltbox_gateway.utils.httpx_client import HttpxClientSingletoneFactory
from saltbox_gateway.utils.rego import ast, sql
from saltbox_gateway.utils.rego.mongo_visitor import MongoQueryVisitor
from saltbox_gateway.utils.rego.sql_visitor import SQLQueryVisitor
from saltbox_sdk.discovery_client.schemas import OPAQueryFilterFormat

type Decision = dict[str, Any]


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

    async def check_access(
        self,
        package: str,
        input: dict,
        *,
        is_partial: bool = False,
        unknowns: list[str] | None = None,
        query_filter_format: OPAQueryFilterFormat | None = None,
        partial_query: str = '',
    ) -> Decision:
        if is_partial:
            return await self.compile(
                package=package,
                input=input,
                unknowns=unknowns or [],
                query_filter_format=query_filter_format or OPAQueryFilterFormat.MONGO,
                partial_query=partial_query or 'allow == true',
            )

        return await self.check_policy(
            package=package,
            input=input,
        )

    async def check_policy(self, package: str, input: dict) -> Decision:
        url = f'{self.base_url}/data/{package.replace(".", "/")}'
        data = {
            'input': input,
        }
        response = await self._client.post(url, json=data, timeout=self.timeout)
        if not response.is_success:
            raise OpaRequestException(response.text)
        result = response.json().get('result', {})
        if not isinstance(result, dict):
            raise OpaResponseFormatException(result)
        if 'allow' not in result:
            msg = 'OPA response does not contain "allow" field'
            raise OpaResponseFormatException(msg)
        if not isinstance(result['allow'], bool):
            msg = '"allow" field in OPA response is not a boolean'
            raise OpaResponseFormatException(msg)
        logger.debug('OPA check policy result: %s', result)
        return result

    async def compile(
        self,
        package: str,
        input: dict,
        unknowns: list[str],
        query_filter_format: OPAQueryFilterFormat | None = None,
        partial_query: str = 'allow == true',
    ) -> dict:
        query_filter_format = query_filter_format or OPAQueryFilterFormat.MONGO
        url = f'{self.base_url}/compile'
        data = {
            'query': f'data.{package}.{partial_query}',
            'input': input,
            'unknowns': ['data.' + u for u in unknowns],
        }

        response = await self._client.post(url, json=data, timeout=self.timeout)
        if not response.is_success:
            raise OpaRequestException(response.text)

        opa_response = response.json().get('result', {})
        if not opa_response:
            return {'allow': False, 'query': None}

        return await self.query_translator(opa_response, query_filter_format)

    async def query_translator(
        self, opa_response: dict, format: OPAQueryFilterFormat = OPAQueryFilterFormat.MONGO
    ) -> dict:
        """Translate a list of queries to a specific format."""
        queries = opa_response.get('queries', [])
        if not queries:
            return {'allow': False, 'query': None}
        if any(len(x) == 0 for x in queries):
            return {'allow': True, 'query': None}

        query_set = ast.QuerySet.from_data(queries)

        if format == OPAQueryFilterFormat.MONGO:
            return await self._compile_to_mongo(query_set)
        if format == OPAQueryFilterFormat.SQL:
            return await self._compile_to_sql(query_set)

    async def _compile_to_mongo(self, query_set: ast.QuerySet) -> dict:
        query_set.preprocess()
        visitor = MongoQueryVisitor()
        query = visitor.visit(query_set)

        return {'allow': True, 'query': query}

    async def _compile_to_sql(self, query_set: ast.QuerySet) -> dict:
        """Compile a query to SQL."""
        sql_visitor = SQLQueryVisitor(from_table='collections')
        clauses = sql_visitor.visit(query_set)
        query = sql.build_sql_query(select='collections.*', from_table='collections', clauses=clauses)

        return {'allow': True, 'query': query}


def get_opa_client() -> AsyncOpaClient:
    """Get an instance of the OPA client."""
    httpx_client = HttpxClientSingletoneFactory.get_instance()
    return AsyncOpaClient(url=SETTINGS.app.opa_url, client=httpx_client)
