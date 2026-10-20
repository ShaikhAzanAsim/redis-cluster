from starlette.status import HTTP_409_CONFLICT


class RecordAlreadyExistException(Exception):
    """Raised when creating a record that conflicts with an existing one.

    Carries an HTTP ``status_code`` so callers can map it directly onto a
    standardized error response without re-deriving the status.
    """

    def __init__(
        self,
        message: str = "A record with the same identity already exists.",
        status_code: int = HTTP_409_CONFLICT,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
