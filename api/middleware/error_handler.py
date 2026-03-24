"""Uniform JSON error responses for HTTPExceptions."""
from fastapi import Request
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
