import pytest

from app.errors import PdfToolError
from app.pagespec import parse


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("all", [0, 1, 2, 3, 4]),
        ("1-3,5", [0, 1, 2, 4]),
        ("3-", [2, 3, 4]),
        ("-2", [0, 1]),
        ("last", [4]),
        ("last-1", [4, 3, 2, 1, 0]),
        ("odd", [0, 2, 4]),
        ("even", [1, 3]),
        ("3,1,1", [2, 0, 0]),
        (" 2 ; 4 ", [1, 3]),
        (None, [0, 1, 2, 3, 4]),
    ],
)
def test_parse(spec, expected):
    assert parse(spec, 5) == expected


@pytest.mark.parametrize("spec", ["0", "6", "a", "1-9", ","])
def test_parse_invalid(spec):
    with pytest.raises(PdfToolError):
        parse(spec, 5)
