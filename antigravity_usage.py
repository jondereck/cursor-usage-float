"""Fetch Antigravity usage and quota from the local language server."""

from __future__ import annotations

import json
import re
import ssl
import time
from dataclasses import dataclass
from typing import Any

import psutil


class AntigravityError(Exception):
    """Raised when Antigravity quota cannot be fetched or parsed."""


@dataclass(frozen=True)
class AntigravityBucket:
    bucket_id: str
    display_name: str
    group_name: str
    remaining_fraction: float
    usage_percent: float
    reset_time: str | None = None


@dataclass(frozen=True)
class AntigravityUsage:
    """Antigravity weekly quota pool (Gemini & 3P models)."""

    usage_percent: float
    gemini_percent: float | None = None
    claude_gpt_percent: float | None = None
    next_reset: str | None = None
    plan_name: str | None = None
    is_eligible: bool = True
    buckets: tuple[AntigravityBucket, ...] = ()


_cached_port: int | None = None
_cached_csrf: str | None = None
_cached_scheme: str | None = None

_ssl_context = ssl.create_default_context()
_ssl_context.check_hostname = False
_ssl_context.verify_mode = ssl.CERT_NONE


def parse_antigravity_quota(payload: dict[str, Any]) -> AntigravityUsage:
    """Parse RetrieveUserQuotaSummary JSON into AntigravityUsage."""
    response = payload.get("response")
    if not isinstance(response, dict):
        # Fallback if wrapped differently
        response = payload

    groups = response.get("groups")
    if not isinstance(groups, list) or not groups:
        raise AntigravityError("Antigravity quota response has no groups.")

    buckets: list[AntigravityBucket] = []
    gemini_pct: float | None = None
    claude_pct: float | None = None
    earliest_reset: str | None = None

    for grp in groups:
        if not isinstance(grp, dict):
            continue
        grp_name = str(grp.get("displayName") or "")
        for b in grp.get("buckets", []):
            if not isinstance(b, dict):
                continue
            bucket_id = str(b.get("bucketId") or "")
            disp_name = str(b.get("displayName") or "")
            rem_frac = float(b.get("remainingFraction", 1.0))
            rem_frac = max(0.0, min(1.0, rem_frac))
            pct = round((1.0 - rem_frac) * 100.0, 1)
            reset = str(b.get("resetTime") or "") or None

            bucket = AntigravityBucket(
                bucket_id=bucket_id,
                display_name=disp_name,
                group_name=grp_name,
                remaining_fraction=rem_frac,
                usage_percent=pct,
                reset_time=reset,
            )
            buckets.append(bucket)

            if "gemini" in bucket_id.lower() or "gemini" in grp_name.lower():
                gemini_pct = pct
                if reset and not earliest_reset:
                    earliest_reset = reset
            elif "3p" in bucket_id.lower() or "claude" in grp_name.lower():
                claude_pct = pct

            if reset and not earliest_reset:
                earliest_reset = reset

    if not buckets:
        raise AntigravityError("No quota buckets found in Antigravity response.")

    # Primary usage: Gemini models if available, otherwise first bucket
    primary_pct = gemini_pct if gemini_pct is not None else buckets[0].usage_percent

    return AntigravityUsage(
        usage_percent=primary_pct,
        gemini_percent=gemini_pct,
        claude_gpt_percent=claude_pct,
        next_reset=earliest_reset,
        is_eligible=True,
        buckets=tuple(buckets),
    )


def _request_quota_summary(
    port: int,
    csrf: str,
    timeout: float = 3.0,
    scheme: str = "https",
) -> dict[str, Any]:
    import urllib.request

    url = f"{scheme}://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary"
    req = urllib.request.Request(
        url,
        data=b"{}",
        headers={
            "Content-Type": "application/json",
            "x-codeium-csrf-token": csrf,
            "Connect-Protocol-Version": "1",
        },
    )
    with urllib.request.urlopen(req, context=_ssl_context, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _discover_language_server() -> tuple[int, str, str]:
    """Find the language server's PID, CSRF token, and working local quota endpoint."""
    servers: list[tuple[int, str]] = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if (proc.info.get("name") or "").lower() != "language_server.exe":
                continue
            cmdline = " ".join(proc.info.get("cmdline") or [])
            match = re.search(r"--csrf_token(?:=|\s+)([a-f0-9\-]+)", cmdline)
            if match:
                servers.append((int(proc.info["pid"]), match.group(1)))
        except (psutil.AccessDenied, psutil.NoSuchProcess, TypeError, ValueError):
            continue

    if not servers:
        raise AntigravityError("Antigravity language_server.exe is not running or its CSRF token is unavailable.")

    deadline = time.monotonic() + 5.0
    last_ports: list[int] = []
    while time.monotonic() < deadline:
        ports: list[int] = []
        for pid, csrf in servers:
            try:
                connections = psutil.Process(pid).net_connections(kind="tcp")
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                continue
            for connection in connections:
                if connection.status != psutil.CONN_LISTEN or not connection.laddr:
                    continue
                address = connection.laddr.ip
                if address not in ("127.0.0.1", "0.0.0.0", "::1", "::"):
                    continue
                port = connection.laddr.port
                if 1 <= port <= 65535 and port not in ports:
                    ports.append(port)
                    for scheme in ("https", "http"):
                        try:
                            _request_quota_summary(port, csrf, timeout=1.0, scheme=scheme)
                            return port, csrf, scheme
                        except Exception:
                            continue

        last_ports = ports

        time.sleep(0.25)

    if not last_ports:
        raise AntigravityError(
            f"No listening ports found for language_server PID {pid} after waiting."
        )
    raise AntigravityError(f"Could not connect to Antigravity on ports {last_ports}.")


def fetch_antigravity_usage() -> AntigravityUsage:
    """Fetch current Antigravity quota usage, using cached port/CSRF if valid."""
    global _cached_port, _cached_csrf, _cached_scheme

    if _cached_port is not None and _cached_csrf is not None and _cached_scheme is not None:
        try:
            data = _request_quota_summary(
                _cached_port,
                _cached_csrf,
                timeout=3.0,
                scheme=_cached_scheme,
            )
            return parse_antigravity_quota(data)
        except Exception:
            _cached_port = None
            _cached_csrf = None
            _cached_scheme = None

    port, csrf, scheme = _discover_language_server()
    _cached_port = port
    _cached_csrf = csrf
    _cached_scheme = scheme

    data = _request_quota_summary(port, csrf, timeout=3.0, scheme=scheme)
    return parse_antigravity_quota(data)
