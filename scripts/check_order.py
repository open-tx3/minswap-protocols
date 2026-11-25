#!/usr/bin/env python3
"""Decode and check a Minswap V2 swap-exact-in order transaction.

Reads an unsigned or signed Cardano transaction (CBOR hex), finds the output
paid to the Minswap V2 order validator, decodes its inline OrderDatum and
compares every protocol field with an expected-effects fixture. Standard
library only, so CI needs nothing beyond Python 3.
"""

import argparse
import copy
import hashlib
import json
import os
import sys

# CBOR (RFC 8949)


class Tag:
    def __init__(self, tag, value):
        self.tag, self.value = tag, value

    def __eq__(self, other):
        return isinstance(other, Tag) and (self.tag, self.value) == (other.tag, other.value)

    def __repr__(self):
        return f"Tag({self.tag}, {self.value!r})"


class Decoder:
    def __init__(self, data):
        self.data, self.pos = data, 0

    def byte(self):
        b = self.data[self.pos]
        self.pos += 1
        return b

    def take(self, n):
        out = self.data[self.pos:self.pos + n]
        if len(out) != n:
            raise ValueError("truncated CBOR")
        self.pos += n
        return out

    def arg(self, info):
        if info < 24:
            return info
        if info in (24, 25, 26, 27):
            return int.from_bytes(self.take(1 << (info - 24)), "big")
        if info == 31:
            return None
        raise ValueError(f"bad CBOR additional info {info}")

    def item(self):
        ib = self.byte()
        major, info = ib >> 5, ib & 31
        n = self.arg(info)
        if major == 0:
            return n
        if major == 1:
            return -1 - n
        if major in (2, 3):
            if n is None:
                chunks = []
                while self.data[self.pos] != 0xFF:
                    chunks.append(self.item())
                self.pos += 1
                raw = b"".join(c if isinstance(c, bytes) else c.encode() for c in chunks)
            else:
                raw = self.take(n)
            return raw if major == 2 else raw.decode()
        if major == 4:
            out = []
            if n is None:
                while self.data[self.pos] != 0xFF:
                    out.append(self.item())
                self.pos += 1
            else:
                out = [self.item() for _ in range(n)]
            return out
        if major == 5:
            out = {}
            count = n
            while (count is None and self.data[self.pos] != 0xFF) or (count is not None and count > 0):
                k = self.item()
                out[freeze(k)] = self.item()
                if count is not None:
                    count -= 1
            if count is None:
                self.pos += 1
            return out
        if major == 6:
            return Tag(n, self.item())
        if major == 7:
            if info == 20:
                return False
            if info == 21:
                return True
            if info in (22, 23):
                return None
            raise ValueError(f"unsupported CBOR simple value {info}")
        raise ValueError("unreachable")


def freeze(k):
    if isinstance(k, list):
        return tuple(freeze(x) for x in k)
    if isinstance(k, Tag):
        return (k.tag, freeze(k.value))
    return k


def cbor_loads(data):
    return Decoder(data).item()


# Plutus data
#
# Every node is decoded against the expected order's exact constructor index
# and arity (lib/amm_dex_v2/types.ak). Some other shapes would also fail the
# validator's typed decode and lock the order; others are valid datums for a
# different order. Both are rejected.


def constr(data):
    """Return (index, fields) for a PlutusData constructor, or raise."""
    if not isinstance(data, Tag):
        raise ValueError(f"expected a constructor, got {data!r}")
    if 121 <= data.tag <= 127:
        return data.tag - 121, list(data.value)
    if 1280 <= data.tag <= 1400:
        return data.tag - 1280 + 7, list(data.value)
    if data.tag == 102:
        return data.value[0], list(data.value[1])
    raise ValueError(f"unexpected tag {data.tag}")


def shape(node, data, allowed):
    """Decode `data` as one of `allowed` {index: arity}; return (index, fields)."""
    try:
        idx, fields = constr(data)
    except (ValueError, TypeError, IndexError) as err:
        raise CheckError(f"datum {node}", str(err))
    if allowed.get(idx) != len(fields):
        raise CheckError(f"datum {node}", f"constructor {idx} with {len(fields)} fields, "
                         f"want one of {sorted(allowed.items())}")
    return idx, fields


def leaf(node, value, kind, size=None):
    ok = isinstance(value, kind) and not isinstance(value, bool)
    if not ok or (size is not None and len(value) != size):
        raise CheckError(f"datum {node}", f"got {value!r}, want {kind.__name__}"
                         + (f" of {size} bytes" if size else ""))
    return value


def plutus_bool(node, data):
    return shape(node, data, {0: 0, 1: 0})[0] == 1


def plutus_credential(node, data):
    idx, (h,) = shape(node, data, {0: 1, 1: 1})
    return {"kind": ["key", "script"][idx], "hash": leaf(node, h, bytes, 28).hex()}


def plutus_address(node, data):
    _, (payment, stake) = shape(node, data, {0: 2})
    s_idx, s_fields = shape(f"{node}.stake", stake, {0: 1, 1: 0})
    stake_out = None
    if s_idx == 0:
        _, (cred,) = shape(f"{node}.stake.inline", s_fields[0], {0: 1})
        stake_out = plutus_credential(f"{node}.stake.credential", cred)
    return {"payment": plutus_credential(f"{node}.payment", payment), "stake": stake_out}


def decode_order_datum(data):
    _, f = shape("OrderDatum", data, {0: 9})
    _, (can,) = shape("canceller", f[0], {0: 1})
    _, (policy, name) = shape("lp_asset", f[5], {0: 2})
    _, (direction, amount, minimum, killable) = shape("step", f[6], {0: 4})
    _, (swap_amount,) = shape("swap_amount_option", amount, {0: 1})
    exp_idx, exp = shape("expiry_setting_opt", f[8], {0: 1, 1: 0})
    expiry = None
    if exp_idx == 0:
        pair = exp[0]
        if not (isinstance(pair, list) and len(pair) == 2):
            raise CheckError("datum expiry_setting_opt", f"got {pair!r}, want (expired_time, max_cancel_tip)")
        expiry = [leaf("expiry_setting_opt", x, int) for x in pair]
    return {
        "canceller": {"method": 0, "hash": leaf("canceller", can, bytes, 28).hex()},
        "refund_receiver": plutus_address("refund_receiver", f[1]),
        "refund_receiver_datum": shape("refund_receiver_datum", f[2], {0: 0})[0],
        "success_receiver": plutus_address("success_receiver", f[3]),
        "success_receiver_datum": shape("success_receiver_datum", f[4], {0: 0})[0],
        "lp_asset": {"policy_id": leaf("lp_asset", policy, bytes, 28).hex(),
                     "asset_name": leaf("lp_asset", name, bytes, 32).hex()},
        "step": {
            "type": 0,
            "a_to_b_direction": plutus_bool("step.a_to_b_direction", direction),
            "swap_amount_option": 0,
            "swap_amount": leaf("swap_amount_option", swap_amount, int),
            "minimum_receive": leaf("step.minimum_receive", minimum, int),
            "killable": plutus_bool("step.killable", killable),
        },
        "max_batcher_fee": leaf("max_batcher_fee", f[7], int),
        "expiry": expiry,
    }


# Transaction


def decode_address(raw):
    header = raw[0]
    kind = header >> 4
    out = {"network_id": header & 0x0F, "payment": None, "stake": None}
    if kind in (0, 1, 2, 3):
        out["payment"] = {"kind": "script" if kind & 1 else "key", "hash": raw[1:29].hex()}
        out["stake"] = {"kind": "script" if kind & 2 else "key", "hash": raw[29:57].hex()}
    elif kind in (6, 7):
        out["payment"] = {"kind": "script" if kind & 1 else "key", "hash": raw[1:29].hex()}
    else:
        raise ValueError(f"unsupported address header {header:#x}")
    return out


def decode_value(v):
    if isinstance(v, int):
        return {"lovelace": v, "assets": {}}
    assets = {}
    for policy, names in v[1].items():
        for name, qty in names.items():
            assets[f"{policy.hex()}.{name.hex()}"] = qty
    return {"lovelace": v[0], "assets": assets}


def decode_output(o):
    if isinstance(o, list):
        addr, value = o[0], o[1]
        datum = {"hash": o[2].hex()} if len(o) > 2 else None
    else:
        addr, value = o[0], o[1]
        datum = None
        if 2 in o:
            kind, body = o[2]
            datum = {"hash": body.hex()} if kind == 0 else {"inline": cbor_loads(body.value)}
    return {"address": decode_address(addr), "value": decode_value(value), "datum": datum}


def decode_tx(cbor_hex):
    tx = cbor_loads(bytes.fromhex(cbor_hex.strip()))
    body = tx[0] if isinstance(tx, list) else tx
    return {"outputs": [decode_output(o) for o in body[1]], "fee": body.get(2)}


def find_order(tx, order_script_hash):
    orders = [o for o in tx["outputs"]
              if o["address"]["payment"] == {"kind": "script", "hash": order_script_hash}]
    if len(orders) != 1:
        raise CheckError("order output", f"expected exactly one order output, found {len(orders)}")
    return orders[0]


def decoded_effects(cbor_hex, order_script_hash):
    """The decoded order output: address, value and OrderDatum."""
    order = find_order(decode_tx(cbor_hex), order_script_hash)
    if not order["datum"] or "inline" not in order["datum"]:
        raise CheckError("datum", "order output carries no inline datum")
    return {
        "address": order["address"],
        "value": order["value"],
        "datum": decode_order_datum(order["datum"]["inline"]),
    }


# Checks


class CheckError(Exception):
    def __init__(self, check, message):
        super().__init__(f"{check}: {message}")
        self.check = check


def lp_asset_name(asset_a, asset_b):
    sha = lambda h: hashlib.sha3_256(bytes.fromhex(h)).hexdigest()
    return sha(sha(asset_a["policy_id"] + asset_a["asset_name"]) + sha(asset_b["policy_id"] + asset_b["asset_name"]))


def check(effects, exp):
    """Raise CheckError naming the first field that differs from `exp`."""
    d, dep, inp = effects["datum"], exp["deployment"], exp["inputs"]
    key = lambda h: {"kind": "key", "hash": h}
    receiver = {"payment": key(inp["trader_pkh"]), "stake": key(inp["trader_stake_key"])}

    def expect(name, got, want):
        if got != want:
            raise CheckError(name, f"got {got!r}, want {want!r}")

    expect("network", effects["address"]["network_id"], dep["network_id"])
    expect("order address stake", effects["address"]["stake"], key(inp["trader_stake_key"]))
    expect("canceller", d["canceller"], {"method": 0, "hash": inp["trader_pkh"]})
    expect("recipient", d["success_receiver"], receiver)
    expect("refund receiver", d["refund_receiver"], receiver)
    expect("receiver datums", (d["success_receiver_datum"], d["refund_receiver_datum"]), (0, 0))

    pool = dep["pool"]
    expect("pool identity", d["lp_asset"], {"policy_id": dep["lp_policy_id"], "asset_name": pool["lp_asset_name"]})
    expect("pool LP name derivation", lp_asset_name(pool["asset_a"], pool["asset_b"]), pool["lp_asset_name"])
    expect("order step", d["step"]["type"], 0)
    # ADA always sorts first, so the ADA/MIN pool has A = ADA and B = MIN.
    expect("pool asset A is ADA", pool["asset_a"], {"policy_id": "", "asset_name": ""})
    expect("pool asset B is MIN", pool["asset_b"], dep["min"])
    expect("asset direction", d["step"]["a_to_b_direction"], True)
    expect("swap amount option", d["step"]["swap_amount_option"], 0)
    expect("swap amount", d["step"]["swap_amount"], inp["swap_amount"])
    expect("minimum return", d["step"]["minimum_receive"], inp["minimum_receive"])
    expect("killable", d["step"]["killable"], False)
    expect("max batcher fee", d["max_batcher_fee"], dep["max_batcher_fee"])
    expect("expiry", d["expiry"], None)
    expect("order lovelace", effects["value"]["lovelace"],
           inp["swap_amount"] + dep["max_batcher_fee"] + dep["order_deposit"])
    expect("order assets", effects["value"]["assets"], {})


def apply_mutation(effects, mutation):
    out = copy.deepcopy(effects)
    *path, last = mutation["path"]
    node = out
    for part in path:
        node = node[part]
    node[last] = mutation["value"]
    return out


def apply_patch(cbor_hex, patch):
    """Replace one byte string in the transaction CBOR; it must occur once."""
    find, replace = patch["find"].lower(), patch["replace"].lower()
    count = cbor_hex.count(find)
    if count != 1 or len(find) != len(replace):
        raise ValueError(f"patch {find} must occur once and keep its length (found {count})")
    return cbor_hex.replace(find, replace)


def run_negative(path, effects, tx_path, cbor_hex, exp):
    """A negative fixture mutates a decoded field or patches the CBOR bytes."""
    neg = json.load(open(path))
    try:
        if "patch" in neg:
            if neg["applies_to"] != os.path.basename(tx_path):
                print(f"FAIL    {path}: patches {neg['applies_to']}, not {tx_path}")
                return 1
            check(decoded_effects(apply_patch(cbor_hex, neg["patch"]), exp["deployment"]["order_script_hash"]), exp)
        else:
            check(apply_mutation(effects, neg["mutation"]), exp)
    except ValueError as err:
        print(f"FAIL    {path}: {err}")
        return 1
    except CheckError as err:
        if err.check != neg["rejects"]:
            print(f"FAIL    {path}: rejected by '{err.check}', want '{neg['rejects']}'")
            return 1
        print(f"ok      {path}: rejected by '{err.check}'")
        return 0
    print(f"FAIL    {path}: mutated order was accepted")
    return 1


def run(args):
    exp = json.load(open(args.expect))
    script_hash = exp["deployment"]["order_script_hash"]
    cbor_hex = open(args.tx).read().strip().lower()
    effects = decoded_effects(cbor_hex, script_hash)
    if args.decode:
        print(json.dumps(effects, indent=2))
        return 0
    check(effects, exp)
    print(f"ok      {args.tx}: order matches {args.expect}")
    failures = sum(run_negative(path, effects, args.tx, cbor_hex, exp) for path in args.negative or [])
    if args.same_as:
        other = decoded_effects(open(args.same_as).read(), script_hash)
        if other != effects:
            print(f"FAIL    {args.tx} and {args.same_as} decode to different orders")
            return 1
        print(f"ok      {args.tx} and {args.same_as} decode to the same order")
    return 1 if failures else 0


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--tx", required=True, help="file holding the transaction CBOR as hex")
    p.add_argument("--expect", required=True, help="expected-effects JSON fixture")
    p.add_argument("--negative", nargs="*", help="negative fixtures (decoded mutations or CBOR patches) "
                   "the checker must reject")
    p.add_argument("--same-as", help="second transaction whose order must decode identically")
    p.add_argument("--decode", action="store_true", help="print the decoded order and exit")
    args = p.parse_args()
    try:
        return run(args)
    except CheckError as err:
        print(f"FAIL    {args.tx}: {err}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
