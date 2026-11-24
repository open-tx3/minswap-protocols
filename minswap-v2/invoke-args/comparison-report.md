# Minswap V2 `place_exact_in_order`: comparison report

Generated 2026-11-24. It compares the unsigned transaction that
`trix invoke --profile preprod --skip-submit` built from
[`place_exact_in_order.json`](place_exact_in_order.json) with an on-chain
preprod order built through Minswap's own tooling for the same trader, pool
and amounts. Both transactions are checked in under [`../fixtures/`](../fixtures/).
[`scripts/check_order.py`](../../scripts/check_order.py) decodes them and
checks every order field against [`expected-effects.json`](../fixtures/expected-effects.json).

## Reference

| | |
|---|---|
| Network | preprod |
| Reference tx | [`e3c9a3473d6a15d1f3f9c521d5847b4dbc6d33d9d651d33bd3a970816b97c10e`](https://preprod.cardanoscan.io/transaction/e3c9a3473d6a15d1f3f9c521d5847b4dbc6d33d9d651d33bd3a970816b97c10e) |
| Block / slot | 5318452 / 136908883 (2026-10-21T14:14:43Z) |
| Builder | Minswap aggregator. Its CIP-20 metadata records the SDK `DexV2` order options: `type: 0` (`SWAP_EXACT_IN`), `direction: 1` (A→B), `killOnFailed: false`, `isLimitOrder: false`, `amountIn: 10000000`, `minimumAmountOut: 892879821`. |
| Constructor | [`DexV2.createBulkOrdersTx`](https://github.com/minswap/sdk/blob/ee95d4317414ae1fe2cdc40549e14a1e185dcf59/src/dex-v2.ts) and [`_swapExactInV2TxExample`](https://github.com/minswap/sdk/blob/ee95d4317414ae1fe2cdc40549e14a1e185dcf59/examples/build-tx-example.ts) |
| Datum schema | [`OrderDatum`](https://github.com/minswap/minswap-dex-v2/blob/c3293ad435792ba502f5a2b1691c6736e5f167e6/lib/amm_dex_v2/types.ak) |
| Deployment | [`deployed/preprod`](https://github.com/minswap/minswap-dex-v2/tree/c3293ad435792ba502f5a2b1691c6736e5f167e6/deployed/preprod) |

The SDK-labelled orders on preprod (`SDK Minswap: Swap Exact In Order`, for
example `53214f39f41c4734e85f26c43ca5923b68ed30fdecd7fb9a32f4ea1c16105820`)
have the same datum shape but target another pool. That is why the reference
is an aggregator order on the ADA/MIN pool.

## Generated

| | |
|---|---|
| Unsigned tx hash | `a58c0ec72db6631be930a7552cedff368521807a567132e2a53a9fd784641367` |
| Resolved | 2026-11-24, public preprod TRP, trix 0.28.0 / tx3c 0.25.0 |
| Spent input | `b4d86e136f58928f8c9247b39a3a351c53505ba03ef6151e92243b18d06f7111#1` (the trader's UTxO at the time) |

## Order output

| Field | Reference (e3c9a347) | Generated (a58c0ec7) | Match |
|---|---|---|---|
| Address payment part | script `da9525…1b7a` (order validator) | script `da9525…1b7a` | yes |
| Address stake part | key `62b2e8…92b8` (trader) | key `62b2e8…92b8` | yes |
| Lovelace | 14,000,000 = 10 ADA offered + 2 ADA batcher fee + 2 ADA deposit | 14,000,000 | yes |
| Other assets | none | none | yes |
| Datum | inline | inline | yes |
| `canceller` | `OAMSignature(f5ea30…ef41)` | same | yes |
| `refund_receiver` | trader base address (`f5ea30…ef41`, `62b2e8…92b8`) | same | yes |
| `refund_receiver_datum` | `EODNoDatum` | same | yes |
| `success_receiver` | trader base address | same | yes |
| `success_receiver_datum` | `EODNoDatum` | same | yes |
| `lp_asset` | `d6aae2…1d0b`.`6c3ea4…1200` (ADA/MIN pool) | same | yes |
| `step` | `SwapExactIn` | `SwapExactIn` | yes |
| `a_to_b_direction` | `true` (ADA → MIN) | `true` | yes |
| `swap_amount_option` | `SAOSpecificAmount(10000000)` | same | yes |
| `minimum_receive` | 892,879,821 (892.879821 MIN) | same | yes |
| `killable` | `false` (pending on failure) | same | yes |
| `max_batcher_fee` | 2,000,000 | same | yes |
| `expiry_setting_opt` | `None` | same | yes |

`check_order.py --same-as` confirms that the two decoded orders are equal.

## Differences outside the order

| Aspect | Reference | Generated | Effect |
|---|---|---|---|
| Datum CBOR | indefinite-length arrays (`d8799f…ff`) | definite-length arrays (`d87989…`) | None. The validator reads the inline datum as data, and both encode the same value. |
| Metadata | CIP-20 `674` message and SDK order options | none | None. The validator ignores metadata. The released TRP cannot yet coerce a nested metadata map (`error coercing Map(...) into Metadatum`), so the interface omits the label. |
| Funding | an input from another address (`addr_test1qq8s55…`) | the trader's own UTxO | None. The order and its receivers are the same. |
| Fee | 214,297 lovelace (ledger minimum) | 1,676,985 lovelace | The hosted preprod TRP adds a fixed 1,500,000 lovelace margin (`extra_fees`) on top of the 176,985 size fee. The trader overpays the network fee, and the order is unchanged. |
| `network_id` body field | absent | `0` | None. |

## Negative fixtures

Each fixture mutates one decoded field of a valid order. The checker must
reject it with the named check:

| Fixture | Mutation | Rejected by |
|---|---|---|
| `wrong-direction.json` | `a_to_b_direction = false` (MIN → ADA) | asset direction |
| `wrong-recipient.json` | success receiver payment hash replaced | recipient |
| `wrong-minimum.json` | `minimum_receive = 1` | minimum return |
| `wrong-pool.json` | `lp_asset` name of another pool | pool identity |
| `wrong-lovelace.json` | 12 ADA locked instead of 14 | order lovelace |

## Refreshing live inputs

The historical fixtures stay reproducible. The live example names the
reference trader's preprod address. If its UTxOs change, a fresh
`trix invoke` spends a different input and produces a different transaction
hash, while the order output decodes the same. To regenerate
`generated-order.cbor.hex`, write the `cbor` field of the invoke output to
that file and rerun the checks.
