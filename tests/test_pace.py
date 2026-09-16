from plugin.wager_bot.errors import is_soft_faucet
from plugin.wager_bot.options import farm_config
from plugin.wager_bot.pace import make_pace


def test_pace_profiles_differ() -> None:
    profiles = [make_pace() for _ in range(20)]
    starts = {item.start_ms for item in profiles}
    tx_hi = {item.tx_to_ms for item in profiles}
    assert len(starts) > 5
    assert len(tx_hi) > 1
    for item in profiles:
        assert 80 <= item.start_ms <= 800
        assert item.step_from_ms <= item.step_to_ms
        assert item.tx_from_ms <= item.tx_to_ms


def test_faucet_cooldown_is_soft() -> None:
    assert is_soft_faucet("cooldown") is True
    assert is_soft_faucet("already_claimed") is True
    assert is_soft_faucet("captcha") is False


def test_defaults_and_bets_cap() -> None:
    cfg = farm_config({})
    assert cfg.vault_usdc_from == 50
    assert cfg.vault_usdc_to == 10000
    try:
        farm_config({"bets_from": 1, "bets_to": 31})
    except ValueError:
        pass
    else:
        raise AssertionError("expected bets above 30 to fail")
    assert farm_config({"bets_from": 1, "bets_to": 30}).bets_to == 30
