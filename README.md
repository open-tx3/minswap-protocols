# minswap-protocols

Tx3 models of Minswap protocols, maintained by TxPipe in the `open-tx3`
organization from Minswap's public contracts, SDK and chain data.

## Protocols

- [`minswap-v2`](./minswap-v2/): place a Minswap V2 swap-exact-in order (ADA → MIN) against the ADA/MIN pool, on preprod.

## Checks

CI runs on pull requests, `main` and version tags. It installs the stable
Tx3 toolchain, runs `trix check` and `trix build`, and runs the semantic
checks in [`scripts/`](./scripts/) against each protocol's fixtures.

## License

[Apache-2.0](./LICENSE).
