#!/usr/bin/env python3
"""Check that the exported TII, profile, fixtures, example and README agree.

Run after `trix build --profile preprod` in minswap-v2/. Checks the exported
operation, parties and preprod profile against the comparison fixture; that
the built TIR is the one the checked-in generated order was resolved from;
that the live example uses the interface's names and is internally consistent;
and that the README names every parameter and links only the release tag.
"""

import hashlib
import json
import pathlib
import re
import sys

TX = "place_exact_in_order"
PARTIES = {"trader", "orderscript"}
ENV_TO_FIXTURE = {
    "order_script_hash": ("order_script_hash",),
    "lp_policy_id": ("lp_policy_id",),
    "pool_lp_asset_name": ("pool", "lp_asset_name"),
    "max_batcher_fee": ("max_batcher_fee",),
    "order_deposit": ("order_deposit",),
}
REPO = "https://github.com/open-tx3/minswap-protocols/"
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


def tir_sha256(tii):
    return hashlib.sha256(tii["transactions"][TX]["tir"]["content"].encode()).hexdigest()


def main(root):
    root = pathlib.Path(root)
    manifest = dict(re.findall(r'^(scope|name|version) = "([^"]+)"', (root / "trix.toml").read_text(), re.M))
    tii_path = root / ".tx3/tii" / manifest["scope"] / manifest["name"] / manifest["version"] / "main.tii"
    tii = json.loads(tii_path.read_text())
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
    historical = fixture["generated"]["args"]
    if set(historical) != params | parties or any(historical[k] != v for k, v in fixture["inputs"].items()):
        errors.append("fixture generated.args do not match the interface's names and the fixture inputs")
    for name in sorted(params | set(ENV_TO_FIXTURE) | {TX}):
        if f"`{name}" not in readme:
            errors.append(f"README does not mention `{name}`")
    tag = f"v{manifest['version']}"
    for ref in re.findall(re.escape(REPO) + r"(?:tree|blob)/([^/)\s]+)", readme):
        if ref != tag:
            errors.append(f"README links the repository at {ref}, not the release tag {tag}")
    if re.search(r"\]\((?!https?://|#)", readme):
        errors.append("README has a relative link, which the registry page cannot resolve")

    env = tii["profiles"].get("preprod", {}).get("environment", {})
    for key, path in ENV_TO_FIXTURE.items():
        want = fixture["deployment"]
        for part in path:
            want = want[part]
        if strip_hex(env.get(key)) != want:
            errors.append(f"preprod env {key}={env.get(key)!r}, fixture has {want!r}")

    built, recorded = tir_sha256(tii), fixture["generated"]["tir_sha256"]
    if built != recorded:
        errors.append(f"built TIR sha256 {built} != {recorded} recorded for the generated order: "
                      "regenerate fixtures/generated-order.cbor.hex (see invoke-args/comparison-report.md)")

    # The live example may name any funded wallet; it only has to be consistent.
    trader = bech32_bytes(example["trader"])
    order = bech32_bytes(example["orderscript"])
    if trader[0] >> 4 != 0 or trader[1:29].hex() != example["trader_pkh"] \
            or trader[29:57].hex() != example["trader_stake_key"]:
        errors.append("trader is not a key/key base address carrying trader_pkh and trader_stake_key")
    if order[0] >> 4 != 1 or order[1:29].hex() != strip_hex(env.get("order_script_hash")) \
            or order[29:57].hex() != example["trader_stake_key"]:
        errors.append("orderscript is not the profile's order script with the trader's stake key")

    for e in errors:
        print(f"FAIL    {e}")
    if not errors:
        print(f"ok      TII exports {TX} with the preprod profile; TIR, fixtures, example and README agree")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
