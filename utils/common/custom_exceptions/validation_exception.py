from starlette.status import HTTP_400_BAD_REQUEST


class ValidationException(Exception):
    """Raised when request input fails business or domain validation.

    Carries an HTTP ``status_code`` so callers can map it directly onto a
    standardized error response without re-deriving the status.
    """

    def __init__(
        self,
        message: str = "The request failed validation.",
        status_code: int = HTTP_400_BAD_REQUEST,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
