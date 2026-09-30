import pytest

from app.api.guards import RateLimiter, client_ip, sniff_image


@pytest.mark.parametrize(
    "head,expected",
    [
        (b"\xff\xd8\xff\xe0rest", "image/jpeg"),
        (b"\x89PNG\r\n\x1a\nrest", "image/png"),
        (b"RIFF\x10\x00\x00\x00WEBPVP8 ", "image/webp"),
        (b"RIFF\x10\x00\x00\x00WAVEfmt ", None),
        (b"GIF89a", None),
        (b"%PDF-1.7", None),
        (b"", None),
    ],
)
def test_sniff_image(head, expected):
    assert sniff_image(head) == expected


def test_rate_limiter_sliding_window():
    rl = RateLimiter(window_s=100)
    assert rl.hit("a", 2, now=0) is None
    assert rl.hit("a", 2, now=10) is None
    assert rl.hit("a", 2, now=20) == pytest.approx(80)
    assert rl.hit("b", 2, now=20) is None
    assert rl.hit("a", 2, now=100.5) is None  # the first hit has aged out
    assert rl.hit("a", 2, now=101) == pytest.approx(9)


class _Req:
    def __init__(self, headers, host="10.0.0.1"):
        self.headers = headers
        self.client = type("C", (), {"host": host})()


@pytest.mark.parametrize(
    "headers,expected",
    [
        ({"cf-connecting-ip": "198.51.100.7"}, "198.51.100.7"),
        ({"cf-connecting-ip": "  "}, "10.0.0.1"),
        ({}, "10.0.0.1"),
    ],
)
def test_client_ip(headers, expected):
    assert client_ip(_Req(headers)) == expected
