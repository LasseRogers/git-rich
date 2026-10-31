"""Phone alerts through ntfy.sh.

Off unless NTFY_TOPIC is set, and each kind can be switched off with ALERT_<KIND>=false.
Anyone who knows the topic can read and send its alerts, so it's treated like a password.
"""
import json
import logging
import os
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

SERVER = "https://ntfy.sh"
KINDS = ("failures", "unmapped_teams", "worse_model", "new_bets")


def send(kind: str, title: str, message: str, priority: int = 3, tags: tuple[str, ...] = ()) -> None:
    """Best effort: an alert that can't be delivered is logged, never raised."""
    if kind not in KINDS:
        raise ValueError(f"unknown alert kind {kind!r}")
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic or os.environ.get(f"ALERT_{kind.upper()}", "true").strip().lower() == "false":
        return
    body = {"topic": topic, "title": title, "message": message, "priority": priority, "tags": list(tags)}
    req = urllib.request.Request(SERVER, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10).close()
    except (urllib.error.URLError, TimeoutError) as e:
        log.warning("%s alert not sent: %s", kind, getattr(e, "reason", e))
