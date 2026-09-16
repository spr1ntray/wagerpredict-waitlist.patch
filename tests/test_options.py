from plugin.wager_bot.config import RunConfig
from plugin.wager_bot.options import farm_config, pick_vault_amount


def test_farm_defaults() -> None:
    cfg = farm_config({})
    assert cfg.bets_from == 10
    assert cfg.bets_to == 14
    assert cfg.bet_usdc_from == 100
    assert cfg.bet_usdc_to == 1000
    assert cfg.vault_tier == 0
    assert cfg.vault_usdc_from == 50
    assert cfg.vault_usdc_to == 10000


def test_farm_rejects_inverted_bets() -> None:
    try:
        farm_config({"bets_from": 6, "bets_to": 2})
    except ValueError as err:
        assert "bets_range" in str(err)
    else:
        raise AssertionError("expected inverted range to fail")


def test_farm_vault_tier() -> None:
    cfg = farm_config({"vault_tier": "lock_180"})
    assert cfg.vault_tier == 2


def test_farm_accepts_large_vault_and_bets() -> None:
    cfg = farm_config(
        {
            "bets_from": 10,
            "bets_to": 30,
            "vault_usdc_from": 500,
            "vault_usdc_to": 15000,
        }
    )
    assert cfg.bets_to == 30
    assert cfg.vault_usdc_to == 15000


def test_vault_amount_is_per_account_random() -> None:
    cfg = RunConfig(vault_usdc_from=50, vault_usdc_to=5000)
    values = {pick_vault_amount(cfg) for _ in range(40)}
    assert len(values) > 1
    assert min(values) >= 50
    assert max(values) <= 5000


def test_bet_raw_spreads_volume_across_remaining() -> None:
    from plugin.wager_bot.options import pick_bet_raw
    from plugin.wager_bot.utils import usdc_to_raw

    cfg = farm_config({"bet_usdc_from": 100, "bet_usdc_to": 1000})
    balance = usdc_to_raw(9000)
    amounts = [pick_bet_raw(cfg, balance, reserve_usdc=500, remaining_bets=10) for _ in range(20)]
    assert min(amounts) >= usdc_to_raw(100)
    assert max(amounts) <= usdc_to_raw(9000 - 500)
    assert max(amounts) >= usdc_to_raw(100)


def test_farm_rejects_inverted_vault() -> None:
    try:
        farm_config({"vault_usdc_from": 400, "vault_usdc_to": 50})
    except ValueError as err:
        assert "vault_usdc_range" in str(err)
    else:
        raise AssertionError("expected inverted vault range to fail")
