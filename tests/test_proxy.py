from plugin.wager_bot.utils import normalize_proxy


def test_hub_four_part_proxy_becomes_http_url() -> None:
    assert (
        normalize_proxy("198.51.100.24:7792:proxy_user:proxy_password")
        == "http://proxy_user:proxy_password@198.51.100.24:7792"
    )


def test_proxy_password_with_special_chars_is_escaped() -> None:
    assert (
        normalize_proxy("10.0.0.1:8000:user:p@ss:word")
        == "http://user:p%40ss%3Aword@10.0.0.1:8000"
    )


def test_already_url_proxy_keeps_scheme_and_escapes() -> None:
    assert (
        normalize_proxy("http://user:p@ss@10.0.0.1:8000")
        == "http://user:p%40ss@10.0.0.1:8000"
    )


def test_raw_hub_proxy_is_not_a_valid_requests_url() -> None:
    raw = "198.51.100.24:7792:proxy_user:proxy_password"
    assert "://" not in raw
    assert normalize_proxy(raw).startswith("http://")
