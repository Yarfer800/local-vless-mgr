#!/usr/bin/env python3
"""
vless-mgr — Parse free VLESS configs, probe them, and patch into Marzban.

Usage:
    python main.py          # Run once and exit
    python main.py --daemon # Run in loop (interval from .env)
    python main.py --help   # Show help
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import socket
import subprocess
import sys

from src.config import Settings
from src.monitor import run_once, run_daemon

# ── ANSI colors ───────────────────────────────────────────
class C:
    CYAN = "\033[36m"
    YELLOW = "\033[33m"
    GREEN = "\033[32m"
    BLUE = "\033[34m"
    DIM = "\033[2m"
    BOLD = "\033[1m"
    RESET = "\033[0m"


def _get_local_ips() -> list[str]:
    """Detect local IP addresses of this machine."""
    ips: set[str] = set()

    try:
        out = subprocess.run(
            ["hostname", "-I"],
            capture_output=True, text=True, timeout=2,
        )
        if out.returncode == 0:
            for ip in out.stdout.strip().split():
                ip = ip.strip()
                if ip and ip not in ("127.0.0.1", "::1"):
                    ips.add(ip)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    try:
        hostname = socket.gethostname()
        ip = socket.gethostbyname(hostname)
        if ip and ip not in ("127.0.0.1", "::1") and not ip.startswith("172."):
            ips.add(ip)
    except (socket.gaierror, OSError):
        pass

    try:
        with open("/etc/hosts") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    parts = line.split()
                    if parts and parts[0] not in ("127.0.0.1", "::1") and not parts[0].startswith("172."):
                        ips.add(parts[0])
    except OSError:
        pass

    return sorted(ips)


def _strip_ansi(s: str) -> str:
    import re
    return re.sub(r"\033\[[0-9;]*m", "", s)


def show_banner(settings: Settings) -> None:
    """Pretty startup banner (pure Python, no rich)."""
    ips = _get_local_ips()
    width = 60

    lines: list[str] = []
    lines.append(f"{C.BOLD}{C.CYAN}  vless-mgr — collector{C.RESET}".center(width - 2))
    lines.append("")

    # Subscription links
    lines.append(f"  {C.YELLOW}Subscription:{C.RESET}")
    sub_urls = ["http://localhost:8080/sub"]
    for ip in ips:
        sub_urls.append(f"http://{ip}:8080/sub")
    for url in sub_urls:
        lines.append(f"    {C.CYAN}🔗  {url}{C.RESET}")
    lines.append("")

    # Marzban links
    if settings.backend in ("marzban", "all") and settings.marzban_url:
        lines.append(f"  {C.YELLOW}Marzban Panel:{C.RESET}")
        marzban_urls = []
        raw = settings.marzban_url.strip().rstrip("/")
        if raw:
            marzban_urls.append(raw)
        marzban_urls.append("http://localhost:8000")
        for ip in ips:
            marzban_urls.append(f"http://{ip}:8000")
        for url in marzban_urls:
            lines.append(f"    {C.CYAN}🔗  {url}{C.RESET}")
        lines.append("")

    # Configuration
    lines.append(f"  {C.BLUE}Configuration:{C.RESET}")
    lines.append(f"    {C.DIM}Backend:{C.RESET}      {settings.backend}")
    lines.append(f"    {C.DIM}Sources:{C.RESET}      {len(settings.sources)}")
    lines.append(f"    {C.DIM}Interval:{C.RESET}     {settings.interval}s")
    lines.append(f"    {C.DIM}Timeout:{C.RESET}      {settings.probe_timeout}s")
    lines.append(f"    {C.DIM}Concurrency:{C.RESET}  {settings.probe_concurrency}")
    lines.append("")
    lines.append(f"  {C.DIM}Ctrl+C to stop{C.RESET}".center(width - 2))

    # ── draw the box ───────────────────────────────────────
    top = f"╭{'─' * (width - 2)}╮"
    bot = f"╰{'─' * (width - 2)}╯"

    out = sys.stderr
    out.write("\n")
    out.write(f"{C.GREEN}{top}{C.RESET}\n")
    for line in lines:
        visible = _strip_ansi(line)
        pad = width - len(visible) - 2
        out.write(f"{C.GREEN}│{C.RESET} {line}{' ' * pad} {C.GREEN}│{C.RESET}\n")
    out.write(f"{C.GREEN}{bot}{C.RESET}\n")
    out.write("\n")
    out.flush()


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="VLESS config collector — fetch, probe, and push to Marzban",
    )
    parser.add_argument(
        "--daemon",
        "-d",
        action="store_true",
        help="Run in daemon mode (loop every INTERVAL seconds)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run once and exit (default)",
    )
    parser.add_argument(
        "--env",
        default=".env",
        help="Path to .env file (default: .env)",
    )
    args = parser.parse_args()

    settings = Settings(_env_file=args.env)
    setup_logging(settings.log_level)

    show_banner(settings)

    if args.daemon:
        asyncio.run(run_daemon(settings))
    else:
        asyncio.run(run_once(settings))


if __name__ == "__main__":
    main()
