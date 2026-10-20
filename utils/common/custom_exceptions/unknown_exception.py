from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR


class UnknownException(Exception):
    """Catch-all for unhandled/unexpected failures.

    Wraps an arbitrary error into a domain exception carrying an HTTP
    ``status_code`` so unexpected cases still surface as a standardized error
    response instead of leaking raw stack traces to the client.
    """

    def __init__(
        self,
        message: str = "An unexpected error occurred. Please try again later.",
        status_code: int = HTTP_500_INTERNAL_SERVER_ERROR,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
