from plugin.wager_bot.config import FAUCET_GAS_WEI, MIN_GAS_WEI, RPC_URLS, SEND_SLOTS
from plugin.wager_bot.errors import safe_code
from plugin.wager_bot.rpc import apply_legacy_fees, broadcast_raw, is_write_rpc, ordered_rpc_urls, write_rpc_urls


def test_workers_dev_is_read_only() -> None:
    assert is_write_rpc("https://predict-rpc-proxy.teamatpredict.workers.dev") is False
    assert is_write_rpc("https://bsc-testnet-rpc.publicnode.com") is True


def test_write_list_skips_read_only_frontends() -> None:
    urls = (
        "https://predict-rpc-proxy.teamatpredict.workers.dev",
        "https://bsc-testnet-rpc.publicnode.com",
        "https://bsc-testnet.bnbchain.org",
    )
    assert write_rpc_urls(urls) == (
        "https://bsc-testnet-rpc.publicnode.com",
        "https://bsc-testnet.bnbchain.org",
    )
    assert ordered_rpc_urls(urls)[0] == "https://bsc-testnet-rpc.publicnode.com"
    assert ordered_rpc_urls(urls)[-1].endswith("workers.dev")


def test_default_rpc_list_has_write_endpoint_first() -> None:
    assert is_write_rpc(RPC_URLS[0]) is True
    assert any("workers.dev" in url for url in RPC_URLS)
    assert write_rpc_urls(RPC_URLS)
    assert SEND_SLOTS >= 8
    assert any("publicnode.com" in url for url in write_rpc_urls(RPC_URLS))
    assert FAUCET_GAS_WEI == 500_000_000_000_000
    assert MIN_GAS_WEI < FAUCET_GAS_WEI


def test_legacy_fees_drop_eip1559_fields() -> None:
    tx = apply_legacy_fees(
        {
            "from": "0xabc",
            "type": 2,
            "gas": 2_000_000,
            "maxFeePerGas": 99,
            "maxPriorityFeePerGas": 2,
        },
        gas_price=100_000_000,
        multiplier=1.25,
    )
    assert tx["gasPrice"] == 125_000_000
    assert tx["gas"] <= 600_000
    assert "type" not in tx
    assert "maxFeePerGas" not in tx
    assert "maxPriorityFeePerGas" not in tx


def test_broadcast_skips_forbidden_rpc() -> None:
    calls: list[str] = []

    def forbidden(_raw: bytes) -> str:
        calls.append("forbidden")
        raise RuntimeError("403 Forbidden")

    def ok(_raw: bytes) -> str:
        calls.append("ok")
        return "0xdead"

    assert broadcast_raw(b"\x01", (forbidden, ok)) == "0xdead"
    assert calls == ["forbidden", "ok"]


def test_broadcast_exhausted_raises_last_error() -> None:
    def boom(_raw: bytes) -> str:
        raise RuntimeError("403 Forbidden")

    try:
        broadcast_raw(b"\x01", (boom,))
    except RuntimeError as exc:
        assert "403" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_sticky_write_rpc_goes_first() -> None:
    from plugin.wager_bot.rpc import preferred_write_urls

    urls = (
        "https://bsc-testnet-rpc.publicnode.com",
        "https://bsc-testnet.bnbchain.org",
        "https://predict-rpc-proxy.teamatpredict.workers.dev",
    )
    ordered = preferred_write_urls(urls, sticky="https://bsc-testnet.bnbchain.org")
    assert ordered[0] == "https://bsc-testnet.bnbchain.org"
    assert "workers.dev" not in "".join(ordered)


def test_write_provider_skips_proxy() -> None:
    from plugin.wager_bot.rpc import provider_kwargs

    proxied = provider_kwargs(30, "http://user:pass@1.2.3.4:1080", direct=False)
    direct = provider_kwargs(30, "http://user:pass@1.2.3.4:1080", direct=True)
    assert "proxies" in proxied
    assert "proxies" not in direct


def test_fitted_gas_price_uses_wallet_dust() -> None:
    from plugin.wager_bot.rpc import fitted_gas_price, parse_have_want

    have, want = parse_have_want(
        RuntimeError("insufficient funds for gas * price + value: have 30000000000000 want 75000000000000")
    )
    assert have == 30_000_000_000_000
    assert want == 75_000_000_000_000
    price = fitted_gas_price(have, gas=200_000)
    assert price == 150_000_000
    assert have >= 200_000 * price
    assert fitted_gas_price(1_000_000, gas=200_000) == 0


def test_affordable_fees_keep_network_price_when_wallet_can_pay() -> None:
    from plugin.wager_bot.rpc import affordable_fees

    gas, price = affordable_fees(100_000_000_000_000, 200_000, 100_000_000)
    assert gas == 200_000
    assert price == 100_000_000


def test_affordable_fees_fit_dust_below_padded_network_cost() -> None:
    from plugin.wager_bot.rpc import affordable_fees

    have = 30_000_000_000_000  # 0.00003 tBNB — меньше 600k * 0.1 gwei
    assert affordable_fees(have, 600_000, 100_000_000) == (0, 0)
    # при оценке без паддинга кошелёк тянет сеть
    gas, price = affordable_fees(have, 200_000, 100_000_000)
    assert gas == 200_000
    assert price == 100_000_000


def test_affordable_fees_zero_when_dust_cannot_pay_floor() -> None:
    from plugin.wager_bot.rpc import affordable_fees

    assert affordable_fees(1_000_000, 200_000, 100_000_000) == (0, 0)


def test_only_native_gas_errors_look_like_gas() -> None:
    from plugin.wager_bot.rpc import is_native_gas_error, rpc_send_hint

    assert is_native_gas_error(RuntimeError("insufficient funds for gas * price + value")) is True
    assert is_native_gas_error(RuntimeError("ERC20: transfer amount exceeds balance")) is False
    assert is_native_gas_error(RuntimeError("insufficient allowance")) is False
    assert "газ" not in rpc_send_hint(RuntimeError("insufficient allowance"))


def test_underpriced_and_cooldown_are_classified() -> None:
    from plugin.wager_bot.errors import faucet_retryable
    from plugin.wager_bot.rpc import is_underpriced

    assert is_underpriced(RuntimeError("replacement transaction underpriced")) is True
    assert is_underpriced(RuntimeError("transaction underpriced")) is True
    assert is_underpriced(RuntimeError("nonce too low")) is False
    assert faucet_retryable("cooldown") is True
    assert faucet_retryable("already_claimed") is False


def test_already_known_is_success() -> None:
    from plugin.wager_bot.rpc import is_already_known, rpc_send_hint

    assert is_already_known(RuntimeError("already known transaction")) is True
    assert is_already_known(RuntimeError("403 Forbidden")) is False
    assert "запретил" in rpc_send_hint(RuntimeError("403 Forbidden"))


def test_send_reject_is_not_estimate_failed() -> None:
    assert safe_code(RuntimeError("tx_rejected: 403 Forbidden")) == "tx_rejected"


def test_blastapi_is_dead_and_not_write() -> None:
    from plugin.wager_bot.rpc import is_write_rpc, write_rpc_urls

    assert is_write_rpc("https://bsc-testnet.public.blastapi.io") is False
    assert all("blastapi" not in url for url in write_rpc_urls(RPC_URLS))


def test_send_uses_every_write_rpc_not_first_three() -> None:
    from plugin.wager_bot.rpc import live_write_urls

    writes = live_write_urls(RPC_URLS)
    assert len(writes) >= 4
    assert any("publicnode" in url for url in writes)
    assert any("drpc.org" in url for url in writes)
    assert writes[-1].endswith("workers.dev") is False


def test_account_proxy_is_tried_before_hub_ip() -> None:
    from plugin.wager_bot.rpc import send_modes

    assert send_modes(None) == (True,)
    assert send_modes("http://user:pass@1.2.3.4:1080") == (False, True)


def test_hard_reject_cools_down_endpoint() -> None:
    from plugin.wager_bot.rpc import (
        clear_send_blocks,
        is_rpc_hard_reject,
        live_write_urls,
        mark_send_blocked,
    )

    clear_send_blocks()
    try:
        assert is_rpc_hard_reject(RuntimeError("403 Forbidden")) is True
        assert is_rpc_hard_reject(RuntimeError("method not allowed: eth_sendRawTransaction")) is True
        assert is_rpc_hard_reject(RuntimeError("Blast API is no longer available")) is True
        assert is_rpc_hard_reject(RuntimeError("insufficient funds for gas * price + value")) is False
        assert is_rpc_hard_reject(RuntimeError("nonce too low")) is False
        bnb = "https://bsc-testnet.bnbchain.org"
        public = "https://bsc-testnet-rpc.publicnode.com"
        mark_send_blocked(bnb)
        assert live_write_urls((bnb, public)) == (public,)
    finally:
        clear_send_blocks()


def test_broadcast_reaches_fourth_rpc_after_three_forbidden() -> None:
    calls: list[str] = []

    def reject(name: str):
        def _fn(_raw: bytes) -> str:
            calls.append(name)
            raise RuntimeError("403 Forbidden")

        return _fn

    def ok(_raw: bytes) -> str:
        calls.append("publicnode")
        return "0xabc"

    assert broadcast_raw(b"\x01", (reject("bnb"), reject("b1"), reject("b2"), ok)) == "0xabc"
    assert calls == ["bnb", "b1", "b2", "publicnode"]
