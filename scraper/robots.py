"""robots.txt parser following RFC 9309 (groups, Allow/Disallow, * and $, longest match).

Written here because common libraries misread some real rules: e.g. BNP Paribas'
`Disallow: *?$` (URLs ending with "?") was understood as "disallow everything".
Same interface as protego: Robots.parse(text).can_fetch(url, agent) / crawl_delay(agent).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit


@dataclass
class _Group:
    agents: list[str] = field(default_factory=list)
    rules: list[tuple[bool, str, re.Pattern]] = field(default_factory=list)  # (allow, raw, regex)
    delay: float | None = None


def _compile(pattern: str) -> re.Pattern:
    anchored = pattern.endswith("$")
    if anchored:
        pattern = pattern[:-1]
    rx = "".join(".*" if ch == "*" else re.escape(ch) for ch in pattern)
    return re.compile(rx + ("$" if anchored else ""), re.S)


class Robots:
    def __init__(self, groups: list[_Group]):
        self.groups = groups

    @classmethod
    def parse(cls, text: str) -> "Robots":
        groups: list[_Group] = []
        cur: _Group | None = None
        last_was_agent = False
        for raw in (text or "").splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            key, val = key.strip().lower(), val.strip()
            if key == "user-agent":
                if cur is None or not last_was_agent:
                    cur = _Group()
                    groups.append(cur)
                cur.agents.append(val.lower())
                last_was_agent = True
                continue
            last_was_agent = False
            if cur is None:
                continue
            if key in ("allow", "disallow"):
                if not val:
                    continue  # empty Disallow = allow everything
                if not val.startswith(("/", "*")):
                    val = "/" + val
                cur.rules.append((key == "allow", val, _compile(val)))
            elif key == "crawl-delay":
                try:
                    cur.delay = float(val)
                except ValueError:
                    pass
        return cls(groups)

    def _groups_for(self, agent: str) -> list[_Group]:
        token = agent.lower().split("/")[0]
        mine = [g for g in self.groups if token in g.agents]   # RFC 9309: product token, case-insensitive
        return mine or [g for g in self.groups if "*" in g.agents]

    def can_fetch(self, url: str, agent: str) -> bool:
        p = urlsplit(url)
        # keep the raw path + query (a bare trailing "?" matters for rules like "*?$")
        rest = url.split("#", 1)[0]
        rest = rest[len(f"{p.scheme}://{p.netloc}"):] if p.netloc else rest
        path = rest or "/"
        if p.path == "/robots.txt":
            return True
        best: tuple[int, bool] | None = None   # (length, allow)
        for g in self._groups_for(agent):
            for allow, raw, rx in g.rules:
                if rx.match(path):
                    cand = (len(raw), allow)
                    if best is None or cand[0] > best[0] or (cand[0] == best[0] and allow):
                        best = cand
        return True if best is None else best[1]

    def crawl_delay(self, agent: str) -> float | None:
        ds = [g.delay for g in self._groups_for(agent) if g.delay is not None]
        return max(ds) if ds else None
