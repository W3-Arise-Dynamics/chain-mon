# chain-mon

Minimal Prometheus exporter for EVM chains. It polls `eth_getBlockByNumber("latest")` on one or more
JSON-RPC endpoints and exposes the latest block number and timestamp.

Block age is intentionally not computed here; derive it in Prometheus (see [PromQL](#promql)).

## Quick start

```sh
cp config.example.yaml config.yaml   # set your RPC URLs
docker compose up -d --build
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
```

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
| `evm_rpc_up` | gauge | `1` if the last poll succeeded, `0` otherwise |
| `evm_rpc_errors_total` | counter | Failed polls |

## PromQL

```promql
# Block age in seconds
time() - evm_latest_block_timestamp_seconds
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
```

Tune the age threshold per chain: block times vary widely between networks.

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
