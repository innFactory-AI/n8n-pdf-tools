"""One error type for everything the caller did wrong (bad input, bad parameters)."""


class PdfToolError(Exception):
    def __init__(self, message: str, code: str = "invalid_request", status: int = 422):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status
