"""Push notifications through ntfy (https://ntfy.sh).

Luca subscribes to his topic in the ntfy app (iPhone / Android / browser).
The topic name is the only secret: it lives in the GitHub secret NTFY_TOPIC.
"""
from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger(__name__)

NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh")


class Notifier:
    def __init__(self, topic: str | None, site_url: str = "", dry_run: bool = False):
        self.topic = topic
        self.site_url = site_url
        self.dry_run = dry_run
        self.sent: list[dict] = []

    def send(self, title: str, message: str, *, priority: int = 3, tags: list[str] | None = None,
             click: str | None = None) -> None:
        msg = {
            "topic": self.topic or "",
            "title": title[:250],
            "message": message[:3800],
            "priority": priority,
            "tags": tags or [],
        }
        if click or self.site_url:
            msg["click"] = click or self.site_url
        self.sent.append(msg)
        if self.dry_run or not self.topic:
            log.info("[notification non envoyée] %s — %s", title, message.replace("\n", " | ")[:300])
            return
        try:
            r = requests.post(NTFY_SERVER, json=msg, timeout=20)
            if r.status_code >= 300:
                log.warning("ntfy %s: %s", r.status_code, r.text[:200])
        except requests.RequestException as e:
            log.warning("ntfy injoignable: %s", e)
