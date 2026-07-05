from __future__ import annotations

import aiohttp
import asyncio
from typing import Optional

from .models import VlessConfig
from .parser import parse_lines


async def fetch_url(session: aiohttp.ClientSession, url: str, timeout: float = 30) -> list[str]:
    """Fetch a single URL and return its lines."""
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            resp.raise_for_status()
            text = await resp.text()
            return [l.strip() for l in text.splitlines() if l.strip()]
    except Exception as exc:
        raise RuntimeError(f"Failed to fetch {url}: {exc}")


async def fetch_configs(
    urls: list[str],
    timeout: float = 30,
    concurrency: int = 5,
) -> tuple[list[VlessConfig], list[str]]:
    """
    Fetch multiple TXT URLs concurrently and parse all VLESS configs.

    Returns (configs, errors).
    """
    connector = aiohttp.TCPConnector(limit=concurrency)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [fetch_url(session, url, timeout) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    all_lines: list[str] = []
    errors: list[str] = []
    for url, result in zip(urls, results):
        if isinstance(result, BaseException):
            errors.append(str(result))
        elif result is not None:
            all_lines.extend(result)

    configs = parse_lines(all_lines)
    return configs, errors
