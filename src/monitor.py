from __future__ import annotations

import asyncio
import logging

from .collector import run_collect
from .config import Settings

log = logging.getLogger(__name__)


async def run_once(settings: Settings) -> None:
    """Run one collection cycle."""
    log.info("=== Collection cycle started ===")
    result = await run_collect(settings)
    log.info(
        "Cycle done: total=%d alive=%d dead=%d pushed=%d errors=%d",
        result.total,
        result.alive,
        result.dead,
        result.pushed,
        len(result.errors),
    )


async def run_daemon(settings: Settings) -> None:
    """Run collection in a loop every INTERVAL seconds."""
    log.info(
        "Starting daemon mode — interval=%ds, backend=%s",
        settings.interval,
        settings.backend,
    )
    while True:
        try:
            await run_once(settings)
        except Exception:
            log.exception("Collection cycle failed")
        log.info("Sleeping for %d seconds...", settings.interval)
        await asyncio.sleep(settings.interval)
