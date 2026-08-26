class ScraperError(Exception):
    pass


class TransientError(ScraperError):
    pass


class RateLimitError(TransientError):
    def __init__(self, retry_after: float | None = None) -> None:
        super().__init__("upstream rate limit reached")
        self.retry_after = retry_after


class UpstreamError(ScraperError):
    def __init__(self, status_code: int, detail: str = "") -> None:
        super().__init__(f"upstream returned {status_code}: {detail}".rstrip(": "))
        self.status_code = status_code


class PayloadError(ScraperError):
    pass
