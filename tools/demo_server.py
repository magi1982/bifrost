"""Run the demo household locally for screenshots and GUI checks: python tools/demo_server.py [port]."""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "tests"))
os.environ["BIFROST_DEV"] = "1"

from bifrost_app.web import serve  # noqa: E402
from demo import build  # noqa: E402

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    svc = build(os.path.join(tempfile.mkdtemp(), "demo.db"))
    serve(svc, port=port).serve_forever()
