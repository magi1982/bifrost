"""Entry point: python -m bifrost_app"""

from __future__ import annotations

import json
import logging
import os
import signal
import threading
from pathlib import Path

from .ha_client import HAClient
from .service import BifrostService
from .store import Store
from .web import serve

DATA = Path(os.environ.get("BIFROST_DATA", "/data"))
DEFAULTS = {"update_interval": 30, "phone_away_minutes": 10, "no_motion_minutes": 15, "shadow_mode": True, "publish_entities": True, "log_level": "info"}


def load_options() -> dict:
    path = DATA / "options.json"
    opts = dict(DEFAULTS)
    if path.exists():
        opts.update(json.loads(path.read_text()))
    return opts


def main() -> None:
    opts = load_options()
    logging.basicConfig(level=getattr(logging, str(opts["log_level"]).upper(), logging.INFO), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("bifrost")
    DATA.mkdir(parents=True, exist_ok=True)
    store = Store(str(DATA / "bifrost.db"))
    service = BifrostService(HAClient(), store, opts)
    httpd = serve(service)
    threading.Thread(target=service.run_forever, name="bifrost-loop", daemon=True).start()

    def shutdown(*_: object) -> None:
        log.info("Stopping Bifrost")
        service.stop()
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    log.info("Bifrost started (shadow mode: %s)", opts["shadow_mode"])
    httpd.serve_forever()
    store.close()


if __name__ == "__main__":
    main()
