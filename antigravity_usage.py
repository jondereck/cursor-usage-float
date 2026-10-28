"""Fetch Antigravity usage and quota from the local language server."""

from __future__ import annotations

import json
import re
import ssl
import subprocess
import time
from dataclasses import dataclass
from typing import Any


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


def _request_quota_summary(port: int, csrf: str, timeout: float = 3.0) -> dict[str, Any]:
    import urllib.request

    url = f"https://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary"
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


def _discover_language_server() -> tuple[int, str]:
    """Find the running language_server.exe PID, CSRF token, and working HTTPS port."""
    ps_script = """
    $p = Get-CimInstance Win32_Process -Filter "name = 'language_server.exe'"
    if ($p) {
        [PSCustomObject]@{
            Id = $p.ProcessId
            CommandLine = $p.CommandLine
        } | ConvertTo-Json
    }
    """
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception as exc:
        raise AntigravityError(f"Failed to query Antigravity process: {exc}") from exc

    stdout = proc.stdout.strip()
    if not stdout:
        raise AntigravityError("Antigravity language_server.exe is not running.")

    try:
        info = json.loads(stdout)
    except Exception as exc:
        raise AntigravityError(f"Could not parse process info: {exc}") from exc

    pid = info.get("Id")
    cmdline = str(info.get("CommandLine") or "")
    if not pid or not cmdline:
        raise AntigravityError("Antigravity language_server.exe process info incomplete.")

    m_csrf = re.search(r"--csrf_token\s+([a-f0-9\-]+)", cmdline)
    if not m_csrf:
        raise AntigravityError("CSRF token not found in language_server command line.")
    csrf = m_csrf.group(1)

    pid_str = str(pid)
    deadline = time.monotonic() + 5.0
    last_ports: list[int] = []
    while time.monotonic() < deadline:
        try:
            netstat_out = subprocess.check_output(
                ["netstat", "-ano", "-p", "tcp"],
                text=True,
                timeout=2,
            )
        except Exception as exc:
            raise AntigravityError(f"Failed to run netstat: {exc}") from exc

        ports: list[int] = []
        for line in netstat_out.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[3] == "LISTENING" and parts[4] == pid_str:
                addr = parts[1]
                if ":" in addr:
                    try:
                        port = int(addr.rsplit(":", 1)[1])
                        if port not in ports:
                            ports.append(port)
                    except ValueError:
                        continue

        last_ports = ports
        for port in ports:
            try:
                _request_quota_summary(port, csrf, timeout=1.0)
                return port, csrf
            except Exception:
                continue

        time.sleep(0.25)

    if not last_ports:
        raise AntigravityError(
            f"No listening ports found for language_server PID {pid} after waiting."
        )
    raise AntigravityError(f"Could not connect to Antigravity on ports {last_ports}.")


def fetch_antigravity_usage() -> AntigravityUsage:
    """Fetch current Antigravity quota usage, using cached port/CSRF if valid."""
    global _cached_port, _cached_csrf

    if _cached_port is not None and _cached_csrf is not None:
        try:
            data = _request_quota_summary(_cached_port, _cached_csrf, timeout=1.0)
            return parse_antigravity_quota(data)
        except Exception:
            _cached_port = None
            _cached_csrf = None

    port, csrf = _discover_language_server()
    _cached_port = port
    _cached_csrf = csrf

    data = _request_quota_summary(port, csrf, timeout=3.0)
    return parse_antigravity_quota(data)
