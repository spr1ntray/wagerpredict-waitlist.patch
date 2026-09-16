from __future__ import annotations

ERC20_ABI = [
    {
        "name": "decimals",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint8"}],
    },
    {
        "name": "balanceOf",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "account", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "name": "allowance",
        "type": "function",
        "stateMutability": "view",
        "inputs": [
            {"name": "owner", "type": "address"},
            {"name": "spender", "type": "address"},
        ],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "name": "approve",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "spender", "type": "address"},
            {"name": "amount", "type": "uint256"},
        ],
        "outputs": [{"name": "", "type": "bool"}],
    },
]

SPOT_ABI = [
    {
        "name": "getBuyQuote",
        "type": "function",
        "stateMutability": "view",
        "inputs": [
            {"name": "id", "type": "uint256"},
            {"name": "side", "type": "uint8"},
            {"name": "usdcIn", "type": "uint256"},
        ],
        "outputs": [
            {"name": "shares", "type": "uint256"},
            {"name": "netIn", "type": "uint256"},
        ],
    },
    {
        "name": "buyShares",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "id", "type": "uint256"},
            {"name": "side", "type": "uint8"},
            {"name": "usdcIn", "type": "uint256"},
            {"name": "minSharesOut", "type": "uint256"},
        ],
        "outputs": [{"name": "shares", "type": "uint256"}],
    },
]

VAULT_ABI = [
    {
        "name": "deposit",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "amount", "type": "uint256"},
            {"name": "tier", "type": "uint8"},
        ],
        "outputs": [{"name": "id", "type": "uint256"}],
    },
]
