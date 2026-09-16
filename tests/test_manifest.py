import json
from pathlib import Path


def _manifest() -> dict:
    path = Path(__file__).resolve().parents[1] / "wagerpredict-testnet" / "hub.plugin.json"
    return json.loads(path.read_text())


def test_contract_and_catalog() -> None:
    manifest = _manifest()
    assert manifest["name"] == "Wager"
    assert manifest["presentation"]["display_name"] == "Wager"
    assert manifest["version"] == "1.17.0"
    assert manifest["presentation"]["description"] == "Кран, ставки, vault и бейджи."
    assert "цепь из hub" not in manifest["presentation"]["description"].lower()
    assert len(manifest["presentation"]["description"]) <= 80
    assert manifest["contract_version"] == "SH-SOFTWARE-0.6/4"
    assert manifest["catalog"]["sections"] == ["testnet"]
    assert manifest["compatibility"]["hub"] == ">=0.6.15"
    risks = {action["risk"] for action in manifest["actions"]}
    assert "testnet_write" in risks
    assert "mainnet_write" not in risks


def test_farm_referral_contract() -> None:
    farm = next(action for action in _manifest()["actions"] if action["id"] == "farm")
    referral = farm["referral"]
    assert referral["mode"] == "project_runtime"
    assert referral["parent_required"] is False
    assert "referral" not in json.dumps(farm["options"]).lower() or "referral_code" not in json.dumps(farm["options"])
    keys = farm["options"]["properties"].keys()
    assert "referral_code" not in keys
    assert "referrer_code" not in keys
    assert "invite" not in keys
    assert "account_concurrency" in keys
    assert "vault_usdc" not in keys
    assert farm["options"]["properties"]["vault_usdc_from"]["maximum"] == 15000
    assert farm["options"]["properties"]["vault_usdc_to"]["maximum"] == 15000
    assert farm["options"]["properties"]["account_concurrency"]["maximum"] == 20
    assert farm["options"]["properties"]["bets_from"]["maximum"] == 30
    assert farm["options"]["properties"]["bets_to"]["maximum"] == 30
    assert farm["options"]["properties"]["bets_from"]["default"] == 10
    assert farm["options"]["properties"]["bets_to"]["default"] == 14
    assert farm["options"]["properties"]["bet_usdc_from"]["default"] == 100
    assert farm["options"]["properties"]["bet_usdc_to"]["default"] == 1000
    assert farm["options"]["properties"]["bet_usdc_from"]["minimum"] == 10
    assert farm["options"]["properties"]["bet_usdc_to"]["maximum"] == 10000
    assert farm["options"]["properties"]["bet_usdc_from"]["multipleOf"] == 10
    assert farm["options"]["properties"]["bet_usdc_to"]["multipleOf"] == 10
    for name, prop in farm["options"]["properties"].items():
        ui = prop.get("x-ui") or {}
        if ui.get("control") not in {"slider", "dual_range"}:
            continue
        step = int(prop.get("multipleOf") or 1)
        steps = (int(prop["maximum"]) - int(prop["minimum"])) // step
        assert 1 <= steps <= 1000, name
    assert farm["options"]["properties"]["vault_usdc_from"]["default"] == 50
    assert farm["options"]["properties"]["vault_usdc_to"]["default"] == 10000
    hosts = set(_manifest()["permissions"]["network"])
    assert "bsc-testnet-rpc.publicnode.com" in hosts
    assert "bsc-testnet.publicnode.com" in hosts
    assert "bsc-testnet.bnbchain.org" in hosts
    assert "bsc-testnet.drpc.org" in hosts
    assert "bsc-testnet.public.blastapi.io" not in hosts
    assert "www.bnbchain.org" in hosts
    assert "testnet.bnbchain.org" in hosts
    assert "bsc-dataseed.binance.org" in hosts
    assert "bsc-rpc.publicnode.com" in hosts
    assert "1rpc.io" in hosts


def test_inspect_is_read_only() -> None:
    inspect = next(action for action in _manifest()["actions"] if action["id"] == "inspect")
    assert inspect["risk"] == "read"
    assert inspect["permissions"]["secrets"] == ["proxy"]
    assert inspect["output"]["primary_kind"] == "account_snapshot"
    assert "slug" not in {col["key"] for col in inspect["output"]["columns"]}
