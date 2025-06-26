from fastapi import Request
from fastapi.responses import JSONResponse


async def custom_http_handler(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=getattr(exc, 'status_code', 500),
        content={
            # 'code': getattr(exc, "code", None),
            # 'title': getattr(exc, "title", None),
            'detail': getattr(exc, 'detail', str(exc)),
        },
    )
