#!/usr/bin/env python3
"""Minimal Prometheus exporter: latest block number and timestamp for EVM chains."""
import argparse
import logging
import os
import signal
import sys
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
RPC_UP = Gauge("evm_rpc_up", "1 if the last latest-block poll succeeded, 0 otherwise", ["chain"])
RPC_ERRORS = Counter("evm_rpc_errors_total", "Failed latest-block polls", ["chain"])
disable_created_metrics()  # drop *_created series

log = logging.getLogger("chain-mon")


class RpcError(Exception):
    """The endpoint answered with a JSON-RPC error object."""


def rpc(session, url, timeout, method, params):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    resp = session.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    body = resp.json()
    if body.get("error"):
        err = body["error"]
        raise RpcError(f"code {err.get('code')}: {err.get('message')}")
    return body["result"]


def get_block(session, url, timeout, tag):
    block = rpc(session, url, timeout, "eth_getBlockByNumber", [tag, False])
    if block is None:
        raise ValueError(f"no {tag} block yet")
    return int(block["number"], 16), int(block["timestamp"], 16)


def poll_finalized(session, url, timeout, name):
    number, timestamp = get_block(session, url, timeout, "finalized")
    FINALIZED_NUMBER.labels(name).set(number)
    FINALIZED_TIMESTAMP.labels(name).set(timestamp)


def poll_peer_count(session, url, timeout, name):
    peers = int(rpc(session, url, timeout, "net_peerCount", []), 16)
    PEER_COUNT.labels(name).set(peers)  # only create the series once a value exists


# Optional, best-effort calls: config key -> (poll function, gauges it sets)
OPTIONAL = {
    "finalized": (poll_finalized, (FINALIZED_NUMBER, FINALIZED_TIMESTAMP)),
    "peer_count": (poll_peer_count, (PEER_COUNT,)),
}


def unsupported(e):
    """True if the endpoint rejected the call itself (method missing or blocked), not a transient error."""
    if isinstance(e, RpcError):
        return True
    if isinstance(e, requests.HTTPError) and e.response is not None:
        return 400 <= e.response.status_code < 500 and e.response.status_code != 429
    return False


def describe(e):
    # never str() a requests exception: it contains the RPC URL (and possibly API keys)
    if isinstance(e, RpcError):
        return str(e)
    if isinstance(e, requests.HTTPError) and e.response is not None:
        return f"HTTP {e.response.status_code}"
    return type(e).__name__


def poll(name, url, interval, timeout, optional):
    session = requests.Session()
    RPC_ERRORS.labels(name)  # export 0 before the first error
    while True:
        try:
            number, timestamp = get_block(session, url, timeout, "latest")
            BLOCK_NUMBER.labels(name).set(number)
            BLOCK_TIMESTAMP.labels(name).set(timestamp)
            RPC_UP.labels(name).set(1)
        except Exception as e:
            RPC_UP.labels(name).set(0)
            RPC_ERRORS.labels(name).inc()
            log.warning("%s: poll failed (%s)", name, describe(e))
            time.sleep(interval)
            continue

        # optional calls never affect evm_rpc_up; a failure only skips that metric
        for key in list(optional):
            func, gauges = OPTIONAL[key]
            try:
                func(session, url, timeout, name)
            except Exception as e:
                if unsupported(e):
                    optional.remove(key)
                    for gauge in gauges:
                        try:
                            gauge.remove(name)
                        except KeyError:
                            pass
                    log.warning(
                        "%s: %s not supported by endpoint, disabled until restart (%s); "
                        "set '%s: false' for this chain to skip the check",
                        name, key, describe(e), key,
                    )
                else:
                    log.warning(
                        "%s: %s poll failed (%s); if the endpoint does not support it, "
                        "set '%s: false' for this chain to disable the check",
                        name, key, describe(e), key,
                    )
        time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # as PID 1 in a container, SIGTERM is ignored unless handled: exit promptly on docker stop
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    with open(args.config) as f:
        cfg = yaml.safe_load(f)
    interval = cfg.get("poll_interval", 15)
    timeout = cfg.get("timeout", 10)
    port = cfg.get("listen_port", 9877)
    for chain in cfg["chains"]:
        if not isinstance(chain.get("name"), str):
            sys.exit(f"chain name must be a string, got {chain.get('name')!r} (quote names like 'on' or 'no')")

    start_http_server(port)
    log.info("listening on :%d, polling %d chain(s) every %ss", port, len(cfg["chains"]), interval)
    for chain in cfg["chains"]:
        url = os.path.expandvars(chain["rpc_url"])
        optional = [key for key in OPTIONAL if chain.get(key, True)]  # all optional calls default on
        threading.Thread(target=poll, args=(chain["name"], url, interval, timeout, optional), daemon=True).start()

    threading.Event().wait()


if __name__ == "__main__":
    main()
