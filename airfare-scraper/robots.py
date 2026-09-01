"""robots.txt gate — RFC 9309 semantics.

Written by hand rather than with urllib.robotparser, which implements the
1994 draft and gets two things wrong that matter here:

  * it treats a blank line as the end of a group, so a file that puts an
    empty line between "User-agent: *" and its rules (ixigo does exactly
    this) parses as having no rules at all — every path reads as allowed;
  * it returns the FIRST matching rule instead of the longest, so a file
    that opens with "Allow: /" (cleartrip) makes every later Disallow
    invisible.

Both failures err towards crawling something we were asked not to, which is
the one direction this must never fail in. Hosts that cannot be reached at
all are treated as disallowed; a 404 means no rules were published, which
the standard says is an allow.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from urllib.parse import unquote, urlparse

import httpx

import config


@dataclass
class _Rule:
    pattern: str
    allow: bool
    regex: "re.Pattern" = field(init=False)

    def __post_init__(self):
        self.regex = _compile(self.pattern)

    @property
    def weight(self) -> int:
        # RFC 9309: the most specific (longest) pattern wins.
        return len(self.pattern)


@dataclass
class _Group:
    agents: List[str] = field(default_factory=list)
    rules: List[_Rule] = field(default_factory=list)
    crawl_delay: Optional[float] = None


def _compile(pattern: str) -> "re.Pattern":
    """robots path pattern -> regex. '*' is any run, '$' anchors the end."""
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    out = "".join(".*" if ch == "*" else re.escape(ch) for ch in body)
    return re.compile("^" + out + ("$" if anchored else ""))


class RobotsFile:
    def __init__(self, text: str):
        self.groups: List[_Group] = []
        current: Optional[_Group] = None
        expecting_agents = False

        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue  # blank lines do NOT end a group (RFC 9309 §2.2)
            field_name, _, value = line.partition(":")
            field_name = field_name.strip().lower()
            value = value.strip()

            if field_name == "user-agent":
                if current is None or not expecting_agents:
                    current = _Group()
                    self.groups.append(current)
                    expecting_agents = True
                current.agents.append(value.lower())
            elif field_name in ("allow", "disallow"):
                if current is None:
                    continue  # rule before any user-agent line: ignore
                expecting_agents = False
                if field_name == "disallow" and value == "":
                    continue  # "Disallow:" with no value means allow everything
                current.rules.append(_Rule(value, field_name == "allow"))
            elif field_name == "crawl-delay" and current is not None:
                expecting_agents = False
                try:
                    current.crawl_delay = float(value)
                except ValueError:
                    pass

    def _group_for(self, agent: str) -> Optional[_Group]:
        agent = agent.lower()
        best: Optional[_Group] = None
        best_len = -1
        wildcard: Optional[_Group] = None
        for group in self.groups:
            for candidate in group.agents:
                if candidate == "*":
                    wildcard = wildcard or group
                elif candidate and agent.startswith(candidate) and len(candidate) > best_len:
                    best, best_len = group, len(candidate)
        return best or wildcard

    def allowed(self, agent: str, path: str) -> bool:
        group = self._group_for(agent)
        if group is None or not group.rules:
            return True
        path = unquote(path) or "/"
        winner: Optional[_Rule] = None
        for rule in group.rules:
            if rule.regex.match(path):
                if (
                    winner is None
                    or rule.weight > winner.weight
                    # tie goes to allow
                    or (rule.weight == winner.weight and rule.allow)
                ):
                    winner = rule
        return winner.allow if winner else True

    def crawl_delay(self, agent: str) -> Optional[float]:
        group = self._group_for(agent)
        return group.crawl_delay if group else None


class RobotsGate:
    """One decision per host, cached for the life of the process."""

    def __init__(self, agent: Optional[str] = None, user_agent: Optional[str] = None):
        self.agent = agent or config.ROBOTS_AGENT
        self.user_agent = user_agent or config.USER_AGENT
        self._cache: Dict[str, Tuple[Optional[RobotsFile], str]] = {}

    def _load(self, url: str) -> Tuple[Optional[RobotsFile], str]:
        parts = urlparse(url)
        host = f"{parts.scheme}://{parts.netloc}"
        if host in self._cache:
            return self._cache[host]

        parsed: Optional[RobotsFile] = None
        try:
            resp = httpx.get(
                f"{host}/robots.txt",
                headers={"User-Agent": self.user_agent},
                timeout=20.0,
                follow_redirects=True,
            )
            if resp.status_code == 200:
                parsed = RobotsFile(resp.text)
                reason = f"robots.txt parsed ({len(parsed.groups)} groups)"
            elif 400 <= resp.status_code < 500:
                reason = f"robots.txt {resp.status_code} — no rules published, allowed"
            else:
                reason = f"robots.txt {resp.status_code} — treating as disallowed"
        except Exception as exc:
            reason = (
                f"robots.txt unreachable ({type(exc).__name__}) — treating as disallowed"
            )

        self._cache[host] = (parsed, reason)
        return self._cache[host]

    def allowed(self, url: str) -> Tuple[bool, str]:
        parsed, reason = self._load(url)
        if parsed is None:
            return ("no rules published" in reason), reason
        parts = urlparse(url)
        path = parts.path + (f"?{parts.query}" if parts.query else "")
        return parsed.allowed(self.agent, path), reason

    def crawl_delay(self, url: str) -> Optional[float]:
        parsed, _ = self._load(url)
        return parsed.crawl_delay(self.agent) if parsed else None
