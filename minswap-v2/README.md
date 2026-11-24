# Minswap V2: place an exact-input order

Place one Minswap V2 swap-exact-in order that offers a fixed amount of ADA for
at least a minimum amount of MIN in the ADA/MIN pool. This Tx3 interface
prepares the order transaction a trader signs. It produces the same order as
the Minswap SDK's V2 constructor (`DexV2.createBulkOrdersTx` with
`OrderV2.StepType.SWAP_EXACT_IN`).

Minswap V2 settles orders in batches. This transaction only **creates** the
order: it pays the offered ADA, the batcher fee and a deposit to the order
validator, with an inline order datum, and runs no script. A Minswap batcher
later spends the order together with the pool in a separate transaction. It
pays at least `minimum_receive` MIN, plus the unused fee and the deposit, to
the trader. If the pool cannot meet the minimum, the order stays open until
the trader cancels it.

## Transactions

| Transaction | Description |
|---|---|
| `place_exact_in_order` | Offer exactly `swap_amount` lovelace for at least `minimum_receive` MIN in the ADA/MIN pool |

## Parties

| Party | Role |
|---|---|
| `Trader` | Funds the order, signs, receives change, and is the order's canceller, success receiver and refund receiver. Must be a base address with a key payment part and a key stake part. |
| `OrderScript` | The order validator address with the trader's stake key: the profile's `order_script_hash` as payment part plus `trader_stake_key`. The SDK derives the same address, so staking rewards on the locked ADA stay with the trader. The caller builds this address; the transaction does not derive or check it, so a wrong address locks the order where no batcher settles it. |

## Parameters and units

| Parameter | Type | Unit and source |
|---|---|---|
| `trader_pkh` | Bytes | The trader's 28-byte payment key hash: the payment part of the `Trader` address. |
| `trader_stake_key` | Bytes | The trader's 28-byte stake key hash: the stake part of the `Trader` address. |
| `swap_amount` | Int | ADA offered, in lovelace (1 ADA = 1,000,000 lovelace). |
| `minimum_receive` | Int | Least MIN accepted, in base units. MIN has 6 decimals, so 1 MIN = 1,000,000. Derive it from the pool reserves and your slippage tolerance, as the SDK example does with `DexV2Calculation.calculateAmountOut`. |

The order locks `swap_amount + max_batcher_fee + order_deposit` lovelace and
no other assets. The trader's wallet must also cover the network fee.

## Deployment (preprod profile)

The `preprod` profile binds the public Minswap V2 preprod deployment:

| Field | Value | Source |
|---|---|---|
| `order_script_hash` | `da9525463841173ad1230b1d5a1b5d0a3116bbdeb4412327148a1b7a` | Order validator: payment part of `orderEnterpriseAddress` and of the `OrderScript` address |
| `lp_policy_id` | `d6aae2059baee188f74917493cf7637e679cd219bdfbbf4dcbeb1d0b` | `lpPolicyId`, also the pool authentication policy |
| `pool_lp_asset_name` | `6c3ea488e6ff940bb6fb1b18fd605b5931d9fefde6440117015ba484cf321200` | ADA/MIN pool identity: `sha3_256(sha3_256(ADA) ++ sha3_256(MIN))` |
| `max_batcher_fee` | `2000000` lovelace | SDK `BATCHER_FEE_DEX_V2[SWAP_EXACT_IN]` |
| `order_deposit` | `2000000` lovelace | SDK `FIXED_DEPOSIT_ADA` |

Other deployment coordinates:

- Order validator: enterprise address `addr_test1wrdf2f2x8pq3wwk3yv936ksmt59rz94mm66yzge8zj9pk7s0kjph3`,
  reference script `8c98f0530cba144d264fbd2731488af25257d7ce6a0cd1586fc7209363724f03#0`
  (used later by the batcher, not by this transaction).
- MIN on preprod: policy `e16c2dc8ae937e8d3790c7fd7168d7b994621ba14ca11415f39fed72`, name `4d494e` (`MIN`).
- ADA/MIN pool: asset A is ADA and asset B is MIN, so the order's
  `a_to_b_direction` is `true`. The pool UTxO was observed at
  `fe784a513b058b68a116c8543173abdbcfc864a1d2407f5df07e685c5ca4ea8f#3` on 2026-11-24.

Only `preprod` is configured. The mainnet deployment publishes different
coordinates and needs its own profile.

## Expected effects

One output at the trader's order address holds exactly
`swap_amount + 4,000,000` lovelace and an inline `OrderDatum`:

| Field | Value |
|---|---|
| `canceller` | `OAMSignature(trader_pkh)` |
| `refund_receiver`, `success_receiver` | the trader's base address (`trader_pkh`, `trader_stake_key`) |
| `refund_receiver_datum`, `success_receiver_datum` | `EODNoDatum` |
| `lp_asset` | `lp_policy_id`.`pool_lp_asset_name` (ADA/MIN pool) |
| `step` | `SwapExactIn { a_to_b_direction: true, SAOSpecificAmount(swap_amount), minimum_receive, killable: false }` |
| `max_batcher_fee` | `2000000` |
| `expiry_setting_opt` | `None` |

A second output returns the change to the trader. Settlement is a later
transaction.

## Example and verification

- [`invoke-args/place_exact_in_order.json`](https://github.com/open-tx3/minswap-protocols/blob/v0.1.0/minswap-v2/invoke-args/place_exact_in_order.json):
  a public input example for live resolution. It names a funded preprod
  wallet; replace it with any funded key/key base address, keeping
  `trader_pkh`, `trader_stake_key` and `orderscript` consistent with it.
- [`fixtures/`](https://github.com/open-tx3/minswap-protocols/tree/v0.1.0/minswap-v2/fixtures): reproducible historical inputs,
  independent of the live example. They hold the owner-built on-chain
  reference order, the Tx3-built unsigned transaction with the arguments and
  the TIR digest it was resolved from, the decoded expected effects with every
  deployment coordinate and source pointer, and negative fixtures: decoded
  mutations (asset direction, recipient, minimum return, pool, locked amount)
  and CBOR patches that break the datum's constructor shapes.
- [`invoke-args/comparison-report.md`](https://github.com/open-tx3/minswap-protocols/blob/v0.1.0/minswap-v2/invoke-args/comparison-report.md):
  a field-by-field comparison with the reference transaction.

```sh
trix check
trix build --profile preprod
python3 ../scripts/check_interface.py .
python3 ../scripts/check_order.py --tx fixtures/generated-order.cbor.hex \
  --expect fixtures/expected-effects.json \
  --same-as fixtures/reference-order.cbor.hex \
  --negative fixtures/negative/*.json fixtures/negative-cbor/*.json
# live resolution against the public preprod TRP (no signing, no submission)
trix invoke --profile preprod --skip-submit \
  --args-json-path invoke-args/place_exact_in_order.json
```

## Use from a client

Pull the published interface, then generate a typed client in any of the six
first-party languages ([consuming guide](https://docs.txpipe.io/tx3/consuming/quick-start)):

```sh
trix use open-tx3/minswap-v2:0.1.0
trix codegen --plugin <plugin>
```

| Language | Codegen plugin | SDK package |
|---|---|---|
| TypeScript | `ts-client` | npm [`tx3-sdk`](https://www.npmjs.com/package/tx3-sdk) |
| Rust | `rust-client` | crates.io [`tx3-sdk`](https://crates.io/crates/tx3-sdk) |
| Go | `go-client` | [`github.com/tx3-lang/go-sdk/sdk`](https://github.com/tx3-lang/go-sdk) |
| Python | `python-client` | PyPI [`tx3-sdk`](https://pypi.org/project/tx3-sdk/) |
| Java | `java-client` | Maven Central [`land.tx3:tx3-sdk`](https://central.sonatype.com/artifact/land.tx3/tx3-sdk) |
| Swift | `swift-client` | SwiftPM [`tx3-lang/swift-sdk`](https://github.com/tx3-lang/swift-sdk), product `Tx3SDK` |

Each generated module exposes a typed `place_exact_in_order` method and the
`preprod` profile. The Tx3 Fluent tools and the Skill for this protocol
version are listed here once they are released.

> **TypeScript:** the TypeScript client generated by tx3c 0.25.0 cannot invoke
> this operation yet. It renames the multi-word parameters (`trader_pkh`,
> `trader_stake_key`, `swap_amount`, `minimum_receive`) before they reach the
> resolver, which then reports them missing. Use another language until a
> fixed tx3c and `tx3-sdk` release.

## Source and license

- Interface source: [`open-tx3/minswap-protocols@v0.1.0`](https://github.com/open-tx3/minswap-protocols/tree/v0.1.0/minswap-v2).
  Each release is tagged; the registry shows the README carried by that tag.
- Minswap V2 contracts and deployment:
  [`minswap/minswap-dex-v2@c3293ad`](https://github.com/minswap/minswap-dex-v2/tree/c3293ad435792ba502f5a2b1691c6736e5f167e6)
  (`deployed/preprod`, `lib/amm_dex_v2/types.ak`), GPL-3.0.
- Minswap SDK: [`minswap/sdk@ee95d43`](https://github.com/minswap/sdk/tree/ee95d4317414ae1fe2cdc40549e14a1e185dcf59)
  (`src/dex-v2.ts`, `examples/build-tx-example.ts` `_swapExactInV2TxExample`), MIT.
- This mapping is TxPipe's reading of those public sources and has not yet
  been reviewed by the Minswap team. It is licensed under
  [Apache-2.0](https://github.com/open-tx3/minswap-protocols/blob/v0.1.0/LICENSE) and contains no code copied from those repositories.
