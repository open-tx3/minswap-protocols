#!/usr/bin/env python3
"""Check that the exported TII, profile, example and README agree.

Run after `trix build --profile preprod` in minswap-v2/. Fails when the TII
lacks the operation or the preprod profile, when the profile's deployment
values differ from the comparison fixture, or when the invoke-args example or
README use names the interface does not export.
"""

import json
import pathlib
import sys

TX = "place_exact_in_order"
PARTIES = {"trader", "orderscript"}
ENV_TO_FIXTURE = {
    "lp_policy_id": ("lp_policy_id",),
    "pool_lp_asset_name": ("pool", "lp_asset_name"),
    "max_batcher_fee": ("max_batcher_fee",),
    "order_deposit": ("order_deposit",),
}
BECH32 = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def bech32_bytes(addr):
    data = [BECH32.index(c) for c in addr.rsplit("1", 1)[1]][:-6]
    acc, bits, out = 0, 0, bytearray()
    for v in data:
        acc, bits = (acc << 5) | v, bits + 5
        if bits >= 8:
            bits -= 8
            out.append((acc >> bits) & 0xFF)
    return bytes(out)


def strip_hex(v):
    return v[2:] if isinstance(v, str) and v.startswith("0x") else v


def main(root):
    root = pathlib.Path(root)
    tii = json.loads(next((root / ".tx3/tii").rglob("main.tii")).read_text())
    fixture = json.loads((root / "fixtures/expected-effects.json").read_text())
    example = json.loads((root / f"invoke-args/{TX}.json").read_text())
    readme = (root / "README.md").read_text()
    errors = []

    if TX not in tii["transactions"]:
        sys.exit(f"FAIL    TII has no transaction {TX}")
    params = set(tii["transactions"][TX]["params"]["properties"])
    parties = set(tii["parties"])
    if parties != PARTIES:
        errors.append(f"parties {sorted(parties)} != {sorted(PARTIES)}")
    if set(example) != params | parties:
        errors.append(f"invoke-args keys {sorted(example)} != params and parties {sorted(params | parties)}")
    if set(fixture["inputs"]) != params:
        errors.append(f"fixture inputs {sorted(fixture['inputs'])} != params {sorted(params)}")
    for name, value in fixture["inputs"].items():
        if example.get(name) != value:
            errors.append(f"invoke-args {name}={example.get(name)!r}, fixture has {value!r}")
    for name in sorted(params | {TX}):
        if f"`{name}" not in readme:
            errors.append(f"README does not mention `{name}`")

    env = tii["profiles"].get("preprod", {}).get("environment", {})
    for key, path in ENV_TO_FIXTURE.items():
        want = fixture["deployment"]
        for part in path:
            want = want[part]
        if strip_hex(env.get(key)) != want:
            errors.append(f"preprod env {key}={env.get(key)!r}, fixture has {want!r}")

    trader = bech32_bytes(example["trader"])
    order = bech32_bytes(example["orderscript"])
    if trader[1:29].hex() != example["trader_pkh"] or trader[29:57].hex() != example["trader_stake_key"]:
        errors.append("trader address does not carry trader_pkh and trader_stake_key")
    if order[0] >> 4 != 1 or order[1:29].hex() != fixture["deployment"]["order_script_hash"] \
            or order[29:57].hex() != example["trader_stake_key"]:
        errors.append("orderscript is not the order script with the trader's stake key")

    for e in errors:
        print(f"FAIL    {e}")
    if not errors:
        print(f"ok      TII exports {TX} with the preprod profile; example, fixture and README agree")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
