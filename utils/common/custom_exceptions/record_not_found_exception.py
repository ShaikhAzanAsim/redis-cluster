from starlette.status import HTTP_404_NOT_FOUND


class RecordNotFoundException(Exception):
    """Raised when a requested record does not exist in the store.

    Carries an HTTP ``status_code`` so callers can map it directly onto a
    standardized error response without re-deriving the status.
    """

    def __init__(
        self,
        message: str = "The requested record was not found.",
        status_code: int = HTTP_404_NOT_FOUND,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
