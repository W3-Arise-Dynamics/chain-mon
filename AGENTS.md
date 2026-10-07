# AGENTS.md

Guidance for coding agents working in this repository.

## Project

`chain-mon` is a minimal Prometheus exporter for EVM chains. It polls
`eth_getBlockByNumber("latest", false)` on each configured JSON-RPC endpoint and exposes the latest
block number and timestamp. Keep it small: the whole exporter lives in `exporter.py`.

| File | Purpose |
|---|---|
| `exporter.py` | Exporter: config loading, one polling thread per chain, metrics HTTP server |
| `config.example.yaml` | Example config (placeholders only) |
| `requirements.txt` | Pinned Python dependencies |
| `Dockerfile`, `docker-compose.yml` | Container build and run (`docker compose up -d --build`) |
| `README.md` | User-facing docs: config, metrics, PromQL, alerts |

## Design rules

- **No derived values in the exporter.** Expose raw facts (block number, block timestamp); derived
  values such as block age are computed in PromQL (`time() - evm_latest_block_timestamp_seconds`).
- **Chains are isolated.** Each chain polls in its own thread; a slow or failing RPC must never delay
  or break another chain.
- **Failures keep last values.** On a failed poll set `evm_rpc_up` to 0 and increment
  `evm_rpc_errors_total`; do not reset block metrics.
- **Never log RPC URLs** or exception messages that may contain them (URLs can embed API keys).
- Metric names use the `evm_` prefix, a `chain` label, and Prometheus naming conventions
  (base units, `_total` for counters, `_seconds` for times).
- Keep dependencies minimal and pinned. Ask before adding a new one.

## Public repo hygiene

This repository is public and must stay generic:

- No real RPC URLs, API keys, IPs, hostnames, usernames or host paths in code, docs or examples.
  Use placeholders such as `https://<ETH_RPC_HOST>` or `${BSC_RPC_URL}`.
- `config.yaml` and `.env` are git-ignored; never commit them or force-add them.

## When changing things

- Keep `README.md` (metrics table, config example) and `config.example.yaml` in sync with code changes.
- New config keys need a default in `exporter.py` and an entry in `config.example.yaml`.

## Verify

```sh
python3 -m py_compile exporter.py
cp config.example.yaml config.yaml   # point at a real endpoint and one bogus URL
docker compose up -d --build
curl -s localhost:9877/metrics | grep evm_
docker compose logs                  # must not contain RPC URLs
docker compose down
```

Expected: the working chain's block number advances between scrapes and its timestamp is close to
`date +%s`; the bogus chain shows `evm_rpc_up 0` and a growing `evm_rpc_errors_total`.
