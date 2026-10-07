#!/usr/bin/env python3
"""Minimal Prometheus exporter: latest block number and timestamp for EVM chains."""
import argparse
import logging
import os
import threading
import time

import requests
import yaml
from prometheus_client import Counter, Gauge, disable_created_metrics, start_http_server

BLOCK_NUMBER = Gauge("evm_latest_block_number", "Latest block number", ["chain"])
BLOCK_TIMESTAMP = Gauge("evm_latest_block_timestamp_seconds", "Unix timestamp of the latest block", ["chain"])
FINALIZED_NUMBER = Gauge("evm_finalized_block_number", "Finalized block number", ["chain"])
FINALIZED_TIMESTAMP = Gauge("evm_finalized_block_timestamp_seconds", "Unix timestamp of the finalized block", ["chain"])
PEER_COUNT = Gauge("evm_peer_count", "Number of peers connected to the node (net_peerCount)", ["chain"])
RPC_UP = Gauge("evm_rpc_up", "1 if the last poll succeeded, 0 otherwise", ["chain"])
RPC_ERRORS = Counter("evm_rpc_errors_total", "Failed polls", ["chain"])
disable_created_metrics()  # drop *_created series

log = logging.getLogger("chain-mon")


def rpc(session, url, timeout, method, params):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    resp = session.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    body = resp.json()
    if body.get("error"):
        raise RuntimeError(f"rpc error: {body['error']}")
    return body["result"]


def get_block(session, url, timeout, tag):
    block = rpc(session, url, timeout, "eth_getBlockByNumber", [tag, False])
    return int(block["number"], 16), int(block["timestamp"], 16)


def poll(name, url, interval, timeout, finalized, peer_count):
    session = requests.Session()
    RPC_ERRORS.labels(name)  # export 0 before the first error
    while True:
        try:
            number, timestamp = get_block(session, url, timeout, "latest")
            BLOCK_NUMBER.labels(name).set(number)
            BLOCK_TIMESTAMP.labels(name).set(timestamp)
            if finalized:
                number, timestamp = get_block(session, url, timeout, "finalized")
                FINALIZED_NUMBER.labels(name).set(number)
                FINALIZED_TIMESTAMP.labels(name).set(timestamp)
            if peer_count:
                PEER_COUNT.labels(name).set(int(rpc(session, url, timeout, "net_peerCount", []), 16))
            RPC_UP.labels(name).set(1)
        except Exception as e:
            RPC_UP.labels(name).set(0)
            RPC_ERRORS.labels(name).inc()
            # log the exception type only: messages may contain the RPC URL (and API keys)
            log.warning("%s: poll failed (%s)", name, type(e).__name__)
        time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    with open(args.config) as f:
        cfg = yaml.safe_load(f)
    interval = cfg.get("poll_interval", 15)
    timeout = cfg.get("timeout", 10)
    port = cfg.get("listen_port", 9877)

    start_http_server(port)
    log.info("listening on :%d, polling %d chain(s) every %ss", port, len(cfg["chains"]), interval)
    for chain in cfg["chains"]:
        url = os.path.expandvars(chain["rpc_url"])
        finalized = chain.get("finalized", True)  # false for chains without the "finalized" tag
        peer_count = chain.get("peer_count", True)  # false for endpoints that block net_peerCount
        threading.Thread(
            target=poll, args=(chain["name"], url, interval, timeout, finalized, peer_count), daemon=True
        ).start()

    threading.Event().wait()


if __name__ == "__main__":
    main()
