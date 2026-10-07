# chain-mon

Minimal Prometheus exporter for EVM chains. It polls `eth_getBlockByNumber("latest")` on one or more
JSON-RPC endpoints and exposes the number and timestamp of the latest and finalized blocks, plus
the node's peer count.

Block age is intentionally not computed here; derive it in Prometheus (see [PromQL](#promql)).

## Quick start

```sh
cp config.example.yaml config.yaml   # set your RPC URLs
docker compose up -d
curl -s localhost:9877/metrics | grep evm_
```

## Configuration

```yaml
listen_port: 9877
poll_interval: 15   # seconds between polls
timeout: 10         # RPC request timeout, seconds

chains:
  - name: ethereum
    rpc_url: https://<ETH_RPC_HOST>
  - name: bsc
    rpc_url: ${BSC_RPC_URL}
    peer_count: false
  - name: example-l2
    rpc_url: https://<L2_RPC_HOST>
    finalized: false
```

Top-level options:

| Key | Required | Default | Description |
|---|---|---|---|
| `listen_port` | no | `9877` | Port of the `/metrics` endpoint |
| `poll_interval` | no | `15` | Seconds between polls of each chain |
| `timeout` | no | `10` | JSON-RPC request timeout, seconds |
| `chains` | yes | | List of chains to monitor |

Per-chain options:

| Key | Required | Default | Description |
|---|---|---|---|
| `name` | yes | | Value of the `chain` label |
| `rpc_url` | yes | | JSON-RPC HTTP endpoint |
| `finalized` | no | `true` | Also poll `eth_getBlockByNumber("finalized")`. Set `false` for chains or clients that don't support the tag |
| `peer_count` | no | `true` | Also poll `net_peerCount`. Set `false` for endpoints that block it (common with hosted providers) |

If any enabled call fails, the whole poll counts as failed (`evm_rpc_up` = 0), so only enable what
the endpoint supports.

`rpc_url` supports `${VAR}` expansion, so API keys can live in a `.env` file next to
`docker-compose.yml` instead of the config. Both `config.yaml` and `.env` are git-ignored.

Each chain is polled in its own thread, so a slow or dead endpoint does not delay the others.
RPC URLs are never logged.

## Metrics

All metrics carry a `chain` label.

| Metric | Type | Description |
|---|---|---|
| `evm_latest_block_number` | gauge | Latest block number |
| `evm_latest_block_timestamp_seconds` | gauge | Unix timestamp of the latest block |
| `evm_finalized_block_number` | gauge | Finalized block number (if `finalized`) |
| `evm_finalized_block_timestamp_seconds` | gauge | Unix timestamp of the finalized block (if `finalized`) |
| `evm_peer_count` | gauge | Peers connected to the node (if `peer_count`) |
| `evm_rpc_up` | gauge | `1` if the last poll succeeded, `0` otherwise |
| `evm_rpc_errors_total` | counter | Failed polls |

## PromQL

```promql
# Latest block age in seconds
time() - evm_latest_block_timestamp_seconds

# Finalized block age in seconds
time() - evm_finalized_block_timestamp_seconds

# Finality lag in blocks
evm_latest_block_number - evm_finalized_block_number
```

Example alert rules:

```yaml
groups:
  - name: chain-mon
    rules:
      - alert: ChainHeadStale
        expr: time() - evm_latest_block_timestamp_seconds > 60
        for: 2m
      - alert: ChainRpcDown
        expr: evm_rpc_up == 0
        for: 2m
      - alert: ChainHeadNotAdvancing
        expr: increase(evm_latest_block_number[5m]) == 0
      - alert: ChainFinalityStale
        expr: time() - evm_finalized_block_timestamp_seconds > 1800
        for: 5m
      - alert: ChainLowPeers
        expr: evm_peer_count < 5
        for: 5m
```

Tune thresholds per chain: block times and finality delays vary widely between networks.

## Prometheus scrape config

```yaml
scrape_configs:
  - job_name: chain-mon
    static_configs:
      - targets: ["<EXPORTER_HOST>:9877"]
```

## Running without Docker

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python exporter.py --config config.yaml
```

## License

MIT, see [LICENSE](LICENSE).
