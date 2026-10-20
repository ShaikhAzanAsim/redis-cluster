class EnvironmentNotSet(Exception):
    """Raised when a required environment variable is missing or empty.

    Config sub-classes raise this during construction so misconfiguration fails
    fast at import time rather than surfacing as an obscure error at runtime.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message
