from __future__ import annotations

import asyncio
import logging
import ssl
import time
from typing import Optional

from .models import VlessConfig, ProbeResult, SecurityType

log = logging.getLogger(__name__)


async def probe_one(
    config: VlessConfig,
    timeout: float = 5.0,
) -> ProbeResult:
    """
    Check if a VLESS server is reachable.

    Does TCP connect + TLS handshake (if security=tls).
    For security=reality: TCP only (Reality doesn't use standard TLS).
    """
    host = config.address
    port = config.port
    start = time.monotonic()

    # 1. DNS resolve
    try:
        async with asyncio.timeout(timeout):
            addrs = await asyncio.get_event_loop().getaddrinfo(host, port)
    except (OSError, asyncio.TimeoutError, TimeoutError) as exc:
        elapsed = (time.monotonic() - start) * 1000
        return ProbeResult(alive=False, error=f"DNS fail: {exc}", latency_ms=round(elapsed, 1))

    if not addrs:
        return ProbeResult(alive=False, error=f"No DNS for {host}")

    needs_tls = config.stream.security in (SecurityType.TLS,)

    last_error: Optional[str] = None
    for _, _, _, _, sockaddr in addrs:
        ip = sockaddr[0]

        # 2. TCP connect
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port),
                timeout=timeout,
            )
        except (OSError, asyncio.TimeoutError, TimeoutError) as exc:
            last_error = str(exc)
            continue

        # 3. TLS handshake (only for security=tls)
        if needs_tls:
            try:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                reader = asyncio.StreamReader()
                protocol = asyncio.StreamReaderProtocol(reader)
                transport, _ = await asyncio.wait_for(
                    asyncio.get_event_loop().create_connection(
                        lambda: protocol,
                        host=ip,
                        port=port,
                        ssl=ctx,
                        sock=writer.transport.get_extra_info("socket"),
                    ),
                    timeout=timeout,
                )
                transport.close()
            except (OSError, asyncio.TimeoutError, TimeoutError, ssl.SSLError) as exc:
                writer.close()
                last_error = f"TLS fail: {exc}"
                continue

        writer.close()
        elapsed = (time.monotonic() - start) * 1000
        return ProbeResult(alive=True, latency_ms=round(elapsed, 1))

    elapsed = (time.monotonic() - start) * 1000
    return ProbeResult(
        alive=False,
        error=last_error or "Connection refused",
        latency_ms=round(elapsed, 1),
    )


async def probe_all(
    configs: list[VlessConfig],
    timeout: float = 5.0,
    concurrency: int = 20,
) -> dict[str, ProbeResult]:
    """Probe all configs via worker queue."""
    results: dict[str, ProbeResult] = {}
    queue: asyncio.Queue[VlessConfig] = asyncio.Queue()
    for cfg in configs:
        await queue.put(cfg)

    total = len(configs)
    done_count = 0
    lock = asyncio.Lock()

    async def _worker() -> None:
        nonlocal done_count
        while True:
            try:
                cfg = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                pr = await asyncio.wait_for(probe_one(cfg, timeout), timeout=timeout + 2)
                async with lock:
                    results[cfg.to_uri()] = pr
                    done_count += 1
                    if done_count % 50 == 0 or done_count == total:
                        log.info("  Probe %d/%d", done_count, total)
            except Exception as exc:
                async with lock:
                    done_count += 1
                    results[cfg.to_uri()] = ProbeResult(alive=False, error=str(exc))
                log.debug("Probe error for %s: %s", cfg.to_uri()[:60], exc)

    workers = [asyncio.create_task(_worker()) for _ in range(min(concurrency, total))]
    await asyncio.gather(*workers)
    log.info("Probing done: %d/%d probes completed", done_count, total)
    return results
