from plugin.wager_bot.errors import BlockedError, SoftError
from plugin.wager_bot.http import ProjectHttp
from plugin.wager_bot.utils import normalize_proxy


def test_soft_error_keeps_public_code() -> None:
    err = SoftError("rate_limited", "API проекта временно ограничило запросы")
    assert err.code == "rate_limited"
    assert "0x" not in err.message


def test_blocked_is_soft() -> None:
    err = BlockedError("invalid_email", "Неверная почта")
    assert isinstance(err, SoftError)
    assert err.code == "invalid_email"


def test_http_uses_browser_origin() -> None:
    http = ProjectHttp(None)
    assert http.session.headers["Origin"] == "https://wagerpredict.com"
    assert http.session.headers["Referer"] == "https://wagerpredict.com/"
    assert "Chrome/142" in http.session.headers["User-Agent"]
    assert http.session.trust_env is False


def test_http_applies_hub_proxy() -> None:
    http = ProjectHttp("198.51.100.24:7792:proxy_user:proxy_password")
    expected = normalize_proxy("198.51.100.24:7792:proxy_user:proxy_password")
    assert http.session.proxies["https"] == expected
