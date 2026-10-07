# AGENTS.md

Guidance for coding agents working in this repository.

## Project

`chain-mon` is a minimal Prometheus exporter for EVM chains. It polls
`eth_getBlockByNumber` (`latest` and `finalized`) on each configured JSON-RPC endpoint and exposes
block numbers and timestamps, plus the node's peer count (`net_peerCount`). Keep it small: the
whole exporter lives in `exporter.py`.

| File | Purpose |
|---|---|
| `exporter.py` | Exporter: config loading, one polling thread per chain, metrics HTTP server |
| `config.example.yaml` | Example config (placeholders only) |
| `requirements.txt` | Pinned Python dependencies |
| `Dockerfile`, `docker-compose.yml` | Container build and run (`docker compose up -d` always builds locally, `pull_policy: build`) |
| `README.md` | User-facing docs: config, metrics, PromQL, alerts |

## Design rules

- **No derived values in the exporter.** Expose raw facts (block numbers, block timestamps, peer
  count); derived values such as block age or finality lag are computed in PromQL
  (`time() - evm_latest_block_timestamp_seconds`).
- **Optional RPC calls are best-effort.** `finalized` and `peer_count` are per-chain toggles
  (default true). Their failures never affect `evm_rpc_up` / `evm_rpc_errors_total`, which track only
  the latest-block call. A call the endpoint rejects (JSON-RPC error, HTTP 4xx except 429) is disabled
  for that chain until restart and its series removed; transient errors just skip that poll.
  To add one, write a `poll_<key>()` function and register it in the `OPTIONAL` table in
  `exporter.py`; the toggle, error handling, series removal and log hint come for free.
- **Warnings must be actionable.** An optional-call warning tells the operator how to silence it
  (`set '<key>: false' for this chain`). Keep that hint when adding or changing log messages.
- **Create a labelled series only once it has a value** (compute first, then `.labels().set()`), so
  unsupported metrics are absent rather than 0.
- **Chains are isolated.** Each chain polls in its own thread; a slow or failing RPC must never delay
  or break another chain.
- **Failures keep last values.** On a failed latest-block poll set `evm_rpc_up` to 0 and increment
  `evm_rpc_errors_total`; do not reset block metrics.
- **Exit promptly on SIGTERM.** The exporter runs as PID 1 in the container, where SIGTERM is
  ignored unless handled; keep the handler in `main()` so `docker stop` doesn't wait for the kill.
- **Validate config before starting the HTTP server** and fail fast with a clear message. Chain names
  must be strings (YAML turns unquoted `on`/`off`/`yes`/`no` into booleans).
- **Never log RPC URLs** or exception messages that may contain them (URLs can embed API keys);
  log via `describe()`, never `str()` of a `requests` exception.
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

Test against real public endpoints: pick several chains and providers from
[chainlist.org](https://chainlist.org) (machine-readable list: `https://chainlist.org/rpcs.json`),
including some that block `net_peerCount`, plus one bogus URL. Keep this in the git-ignored
`config.yaml`; never commit test endpoints.

```sh
python3 -m py_compile exporter.py
docker compose up -d                 # always rebuilds (pull_policy: build)
curl -s localhost:9877/metrics | grep evm_
docker compose logs                  # must not contain RPC URLs
time docker compose stop             # should return in well under a second
docker compose down
```

Expected:

- Working chains: latest block number advances between scrapes, timestamp close to `date +%s`;
  finalized metrics present where supported.
- Endpoints blocking `net_peerCount`: `evm_rpc_up 1`, no `evm_peer_count` series, one
  "not supported ... set 'peer_count: false'" warning.
- Bogus URL: `evm_rpc_up 0` and a growing `evm_rpc_errors_total`.
- HTTP 429 from rate-limited public endpoints is transient and must not disable any check.
