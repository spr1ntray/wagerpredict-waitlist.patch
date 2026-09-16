from __future__ import annotations

from dataclasses import dataclass, field

CHAIN_ID = 97
API_ORIGIN = "https://wagerpredict.com"
API_BASE = "https://api.predictprotocol.app"
TURNSTILE_SITEKEY = "0x4AAAAAADoMI0c92v4dipEe"
TURNSTILE_PAGE = f"{API_ORIGIN}/app"

USDC = "0x0b505F47Ac4f4eeaA10F3f67135085b23AFb7840"
SPOT = "0x1106f999677ab6C43864cD5Ff9CD91e8667BCeBb"
VAULT = "0x1E8fC0326F6E219ff594e6d669C11E47fE667Cf4"
USDC_DECIMALS = 6
FAUCET_USDC = 10_000
MIN_BET_USDC = 1
BETS_MAX = 30
MIN_VAULT_USDC = 10
VAULT_USDC_MAX = 15_000
SEND_SLOTS = 8
FAUCET_SLOTS = 3
MIN_GAS_WEI = 80_000_000_000_000  # 0.00008 tBNB — запас на 600k gas * 0.1 gwei
FAUCET_GAS_WEI = 500_000_000_000_000  # 0.0005 tBNB — ответ /api/faucet/gas amountWei
FAUCET_WAIT_ATTEMPTS = 30
MAX_UINT = 2**256 - 1

# LMSRMath.Side — Solidity enum starts at 0.
SIDE_YES = 0
SIDE_NO = 1

VAULT_TIERS = {
    "flexible": 0,
    "lock_90": 1,
    "lock_180": 2,
    "lock_365": 3,
}

RPC_URLS = (
    "https://bsc-testnet.bnbchain.org",
    "https://data-seed-prebsc-1-s1.binance.org:8545",
    "https://data-seed-prebsc-2-s1.binance.org:8545",
    "https://bsc-testnet-rpc.publicnode.com",
    "https://bsc-testnet.drpc.org",
    "https://bsc-testnet.publicnode.com",
    "https://predict-rpc-proxy.teamatpredict.workers.dev",
)


@dataclass(frozen=True)
class RunConfig:
    request_timeout: int = 30
    receipt_timeout: int = 90
    gas_multiplier: float = 1.25
    bets_from: int = 10
    bets_to: int = 14
    bet_usdc_from: int = 100
    bet_usdc_to: int = 1000
    vault_usdc_from: int = 50
    vault_usdc_to: int = 10000
    vault_tier: int = 0
    pause_from_ms: int = 800
    pause_to_ms: int = 2400
    rpc_urls: tuple[str, ...] = field(default_factory=lambda: RPC_URLS)
