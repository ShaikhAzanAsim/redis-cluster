from typing import Any, Generic, TypeVar

from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.status import HTTP_200_OK


class CommonResponse(BaseModel):
    IsSuccess: bool
    Message: str
    Data: Any | None = None
    Exception: Any | None = None
    StatusCode: int


T = TypeVar("T")


class CommonJSONResponse(JSONResponse, Generic[T]):
    def __init__(
        self,
        is_success: bool,
        message: str,
        data: T | Any = None,
        exception: Any = None,
        status_code: int = HTTP_200_OK,
    ):
        super().__init__(
            content={
                "IsSuccess": is_success,
                "Message": message,
                "Data": data,
                "Exception": exception,
                "StatusCode": status_code,
            },
            status_code=status_code,
        )
