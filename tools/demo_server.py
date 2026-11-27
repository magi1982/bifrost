"""Run the demo household locally for screenshots and GUI checks: python tools/demo_server.py [port]."""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "tests"))
os.environ["BIFROST_DEV"] = "1"

import threading  # noqa: E402
import time  # noqa: E402
from datetime import UTC, datetime  # noqa: E402

from demo import build, demo_adverts, demo_bluetooth  # noqa: E402

from bifrost_app.web import serve  # noqa: E402

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    svc = build(os.path.join(tempfile.mkdtemp(), "demo.db"))
    demo_bluetooth(svc)
    svc.evaluate()
    svc.learn_job(datetime.now(UTC))

    def feed():
        n = 0
        while True:
            time.sleep(4)
            svc.ble.tracker.ingest(demo_adverts())
            n += 1
            if n % 4 == 0:
                svc.evaluate()

    threading.Thread(target=feed, daemon=True).start()
    serve(svc, port=port).serve_forever()
