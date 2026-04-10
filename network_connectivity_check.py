#!/usr/bin/env python3
"""Host and network connectivity snapshot (stdlib only).

Useful for quick diagnostics: local routing, DNS, TCP reachability, optional ICMP,
and optional public IP discovery (HTTPS).
"""

from __future__ import annotations

import argparse
import json
import platform
import socket
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from typing import Any


def _primary_local_ip() -> str | None:
    """Return a plausible LAN/WAN-facing IPv4 using a UDP socket (no traffic sent)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return None


def _public_ip(timeout: float = 5.0) -> str | None:
    for url in (
        "https://api.ipify.org",
        "https://ifconfig.me/ip",
    ):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "network_connectivity_check/1.0"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode().strip()
        except (urllib.error.URLError, OSError):
            continue
    return None


def _dns_resolution(host: str = "example.com") -> dict[str, Any]:
    try:
        infos = socket.getaddrinfo(host, None)
        addrs = sorted({x[4][0] for x in infos})
        return {"host": host, "ok": True, "addresses": addrs}
    except socket.gaierror as exc:
        return {"host": host, "ok": False, "error": str(exc)}


def _tcp_probe(host: str, port: int, timeout: float = 3.0) -> dict[str, Any]:
    try:
        socket.create_connection((host, port), timeout=timeout).close()
        return {"host": host, "port": port, "reachable": True}
    except OSError as exc:
        return {"host": host, "port": port, "reachable": False, "error": str(exc)}


def _tls_handshake(host: str, port: int = 443, timeout: float = 5.0) -> dict[str, Any]:
    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((host, port), timeout=timeout) as raw:
            with ctx.wrap_socket(raw, server_hostname=host) as tls:
                cert = tls.getpeercert()
                return {
                    "host": host,
                    "port": port,
                    "ok": True,
                    "cipher": tls.cipher(),
                    "subject": cert.get("subject") if isinstance(cert, dict) else None,
                }
    except OSError as exc:
        return {"host": host, "port": port, "ok": False, "error": str(exc)}


def _ping_once(host: str, timeout_sec: float = 4.0) -> dict[str, Any]:
    system = platform.system().lower()
    if system == "windows":
        cmd = ["ping", "-n", "1", "-w", str(int(timeout_sec * 1000)), host]
    else:
        cmd = ["ping", "-c", "1", host]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec + 2.0,
        )
        return {
            "host": host,
            "exit_code": proc.returncode,
            "ok": proc.returncode == 0,
        }
    except FileNotFoundError:
        return {"host": host, "ok": False, "error": "ping not found in PATH"}
    except subprocess.TimeoutExpired:
        return {"host": host, "ok": False, "error": "timeout"}


def _interface_names() -> list[str]:
    try:
        return sorted(name for _idx, name in socket.if_nameindex())
    except OSError:
        return []


def gather(*, include_public_ip: bool = True, include_ping: bool = True) -> dict[str, Any]:
    out: dict[str, Any] = {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "hostname": socket.gethostname(),
        "fqdn": socket.getfqdn(),
        "interface_names": _interface_names(),
        "ipv4_udp_route_hint": _primary_local_ip(),
        "dns": _dns_resolution("example.com"),
        "tcp": {
            "cloudflare_https": _tcp_probe("1.1.1.1", 443),
            "google_dns": _tcp_probe("8.8.8.8", 53),
        },
        "tls": {
            "cloudflare": _tls_handshake("one.one.one.one", 443),
        },
    }
    if include_public_ip:
        out["public_ip_https"] = _public_ip()
    else:
        out["public_ip_https"] = None
    if include_ping:
        out["icmp_ping"] = {"one_one_one_one": _ping_once("1.1.1.1")}
    else:
        out["icmp_ping"] = {"skipped": True}
    return out


def _print_human(data: dict[str, Any]) -> None:
    print("Network connectivity check")
    print("-" * 40)
    print(f"Host: {data['hostname']} ({data['fqdn']})")
    print(f"IPv4 (route hint): {data['ipv4_udp_route_hint']}")
    if data.get("public_ip_https"):
        print(f"Public IP (HTTPS): {data['public_ip_https']}")
    dns = data["dns"]
    if dns.get("ok"):
        print(f"DNS {dns['host']}: {', '.join(dns['addresses'])}")
    else:
        print(f"DNS failed: {dns.get('error')}")
    for name, row in data["tcp"].items():
        status = "ok" if row.get("reachable") else f"fail ({row.get('error', '?')})"
        print(f"TCP {name}: {status}")
    tls = data["tls"]["cloudflare"]
    print(f"TLS one.one.one.one: {'ok' if tls.get('ok') else tls.get('error', 'fail')}")
    ping = data.get("icmp_ping", {})
    if "one_one_one_one" in ping:
        p = ping["one_one_one_one"]
        print(f"ICMP 1.1.1.1: {'ok' if p.get('ok') else p.get('error', 'fail')}")
    if data.get("interface_names"):
        print(f"Interfaces: {', '.join(data['interface_names'])}")
    print("-" * 40)
    print("(Use --json for machine-readable output.)")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gather host identity, DNS, TCP/TLS reachability, and optional public IP.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON only (default prints human summary and JSON block).",
    )
    parser.add_argument(
        "--no-public-ip",
        action="store_true",
        help="Skip HTTPS lookup of public IP.",
    )
    parser.add_argument(
        "--no-ping",
        action="store_true",
        help="Skip ICMP ping subprocess.",
    )
    args = parser.parse_args()
    data = gather(
        include_public_ip=not args.no_public_ip,
        include_ping=not args.no_ping,
    )
    if args.json:
        print(json.dumps(data, indent=2))
        return 0
    _print_human(data)
    print()
    print(json.dumps(data, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
