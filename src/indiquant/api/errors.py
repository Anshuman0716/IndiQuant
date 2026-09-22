from fastapi import Request
from fastapi.responses import JSONResponse
from .models import ErrorResponse

async def rfc7807_exception_handler(request: Request, exc: Exception, status_code: int = 500, title: str = "Internal Server Error"):
    err = ErrorResponse(
        type="about:blank",
        title=title,
        status=status_code,
        detail=str(exc),
        instance=str(request.url),
        data_as_of=None
    )
    return JSONResponse(status_code=status_code, content=err.model_dump())
