import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
for key in ("public_sources_enabled", "agent_enabled", "timezone_confirmed"):
    if "PDP_" + key.upper() in os.environ:
        CONFIG[key] = os.environ["PDP_" + key.upper()].lower() in ("true", "1")
DATA = Path(os.environ.get("PDP_DATA_ROOT") or ROOT / CONFIG["data_root"]).resolve()
PORT = int(os.environ.get("PDP_PORT", CONFIG["port"]))
ORIGIN = f"http://127.0.0.1:{PORT}"
MAX_UPLOAD = 12 * 1024 * 1024


def directories():
    for part in ("database", "assets", "exports", "backups", "runtime", "agent-work"):
        (DATA / part).mkdir(parents=True, exist_ok=True)
