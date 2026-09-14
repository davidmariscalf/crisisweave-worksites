#!/usr/bin/env python3
from __future__ import annotations

import os

from server_runtime import BoundedThreadingHTTPServer
from worksites import APIHandler, WorksiteStore, parse_origin


def build_hardened_server(
    store,
    host="127.0.0.1",
    port=8787,
    token=None,
    allowed_origin=None,
    max_workers=32,
    socket_timeout=10.0,
):
    handler = type("BoundHardenedAPIHandler", (APIHandler,), {})
    handler.store = store
    handler.token = token or None
    handler.allowed_origin = parse_origin(allowed_origin)
    return BoundedThreadingHTTPServer(
        (host, int(port)),
        handler,
        max_workers=max_workers,
        socket_timeout=socket_timeout,
    )


def main() -> int:
    store = WorksiteStore(os.getenv("CW_DB", "/data/worksites.db"))
    server = build_hardened_server(
        store,
        os.getenv("CW_HOST", "127.0.0.1"),
        int(os.getenv("CW_PORT", "8787")),
        os.getenv("CW_COORDINATOR_TOKEN") or None,
        os.getenv("CW_WORKSITES_ALLOWED_ORIGIN") or None,
        int(os.getenv("CW_MAX_HTTP_WORKERS", "32")),
        float(os.getenv("CW_HTTP_SOCKET_TIMEOUT", "10")),
    )
    print(f"CrisisWeave worksites API on http://{server.server_address[0]}:{server.server_address[1]}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
