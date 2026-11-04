"""Page selection syntax shared by all endpoints.

Pages are 1-based. A spec is a comma-separated list of tokens:

    all | odd | even | last | N | N-M | N- | N-last
    (N > M yields the pages in reverse order, e.g. "last-1" reverses the document)

parse() returns 0-based indices in the given order (duplicates are kept).
"""

from .config import settings
from .errors import PdfToolError


def _num(token: str, n: int) -> int:
    token = token.strip().lower()
    if token in ("last", "z"):
        return n
    if not token.isdigit():
        raise PdfToolError(f"invalid page '{token}'", "invalid_pages")
    value = int(token)
    if value < 1 or value > n:
        raise PdfToolError(f"page {value} out of range (document has {n} pages)", "invalid_pages")
    return value


def parse_token(token: str, n: int) -> list[int]:
    token = token.strip().lower()
    if token == "all":
        return list(range(n))
    if token == "odd":
        return list(range(0, n, 2))
    if token == "even":
        return list(range(1, n, 2))
    if "-" in token:
        start_raw, end_raw = token.split("-", 1)
        start = _num(start_raw, n) if start_raw.strip() else 1
        end = _num(end_raw, n) if end_raw.strip() else n
        step = 1 if end >= start else -1
        return [p - 1 for p in range(start, end + step, step)]
    return [_num(token, n) - 1]


def tokens(spec: str) -> list[str]:
    parts = [t for t in (spec or "").replace(";", ",").split(",") if t.strip()]
    if len(parts) > settings.max_pages:
        raise PdfToolError(f"page selection has more than {settings.max_pages} tokens", "invalid_pages")
    if not parts:
        raise PdfToolError("empty page selection", "invalid_pages")
    return parts


def parse(spec: str | None, n: int, default: str = "all") -> list[int]:
    spec = spec if spec and spec.strip() else default
    limit = max(n, settings.max_pages)
    result: list[int] = []
    for token in tokens(spec):
        result.extend(parse_token(token, n))
        if len(result) > limit:
            raise PdfToolError(f"page selection exceeds {limit} pages", "invalid_pages")
    return result


def parse_set(spec: str | None, n: int, default: str = "all") -> set[int]:
    return set(parse(spec, n, default))
