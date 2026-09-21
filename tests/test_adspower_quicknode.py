from plugin.wager_bot.adspower_quicknode import (
    ADSPOWER_LOCAL,
    QUICKNODE_FAUCET_URL,
    duplicate_adspower_ids,
)


def test_quicknode_url_is_bnb_testnet() -> None:
    assert "binance-smart-chain" in QUICKNODE_FAUCET_URL
    assert "bnb-testnet" in QUICKNODE_FAUCET_URL
    assert ADSPOWER_LOCAL.startswith("http://local.adspower.net")


def test_duplicate_adspower_ids() -> None:
    assert duplicate_adspower_ids([("a", "p1"), ("b", "p2")]) == set()
    assert duplicate_adspower_ids([("a", "p1"), ("b", "p1")]) == {"a", "b"}
    assert duplicate_adspower_ids([("a", ""), ("b", "")]) == set()
