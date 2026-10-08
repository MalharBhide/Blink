"""Owner-only, short-lived launch pairing. Never puts the permanent access code in a URL."""

import json
import secrets
import threading
import time
from backend.app.config import settings

_LOCK = threading.Lock()


def consume_launch_ticket(candidate: str) -> bool:
    if not candidate or len(candidate) > 128:
        return False
    path = settings().data_dir / "launch-ticket"
    with _LOCK:
        try:
            if path.stat().st_size > 512:
                return False
            item = json.loads(path.read_text())
            expiry = float(item["expires_at"])
            valid = time.time() < expiry <= time.time() + 125 and secrets.compare_digest(
                candidate, str(item["ticket"])
            )
            if valid:
                path.unlink()  # Atomic consume under the lock: a link can unlock only once.
            return valid
        except (OSError, ValueError, KeyError, TypeError):
            return False
