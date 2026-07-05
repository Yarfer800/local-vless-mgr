from __future__ import annotations

import asyncio
import json
import logging
import pathlib
import random

from .config import Settings
from .models import VlessConfig, ProbeResult, RunResult, SecurityType, StreamNetwork
from .fetcher import fetch_configs
from .prober import probe_all
from .backends import Backend
from .backends.json_file import JsonBackend
from .backends.marzban import MarzbanBackend
from .backends.xray_outbound import XrayOutboundBackend

log = logging.getLogger(__name__)


async def create_backend(settings: Settings) -> Backend:
    """Factory: create the configured backend."""
    backend_name = settings.backend.lower()

    if backend_name == "marzban":
        if not settings.marzban_url:
            raise ValueError("MARZBAN_URL is required for marzban backend")
        return MarzbanBackend(
            base_url=settings.marzban_url,
            username=settings.marzban_username,
            password=settings.marzban_password,
            remark_prefix=settings.inbound_remark_prefix,
        )

    if backend_name == "xray":
        return XrayOutboundBackend()

    if backend_name == "all":
        backends: list[Backend] = [JsonBackend(), XrayOutboundBackend()]
        if settings.marzban_url:
            backends.append(MarzbanBackend(
                base_url=settings.marzban_url,
                username=settings.marzban_username,
                password=settings.marzban_password,
                remark_prefix=settings.inbound_remark_prefix,
            ))
        return _MultiBackend(backends)

    return JsonBackend()


class _MultiBackend(Backend):
    """Runs multiple backends in parallel."""

    def __init__(self, backends: list[Backend]) -> None:
        self._backends = backends

    async def initialize(self) -> None:
        for b in self._backends:
            await b.initialize()

    async def cleanup(self) -> None:
        for b in self._backends:
            await b.cleanup()

    async def publish(self, alive: dict[str, tuple[VlessConfig, ProbeResult]], state: dict) -> int:
        results = await asyncio.gather(
            *[b.publish(alive, state) for b in self._backends],
            return_exceptions=True,
        )
        total = 0
        for r in results:
            if isinstance(r, int):
                total += r
            elif isinstance(r, Exception):
                log.error("Backend error: %s", r)
        return total


# ── Subscription file writer + GeoIP ──────────────────────

COUNTRY_FLAGS: dict[str, str] = {
    "RU": "🇷🇺", "US": "🇺🇸", "DE": "🇩🇪", "FR": "🇫🇷", "GB": "🇬🇧",
    "NL": "🇳🇱", "CA": "🇨🇦", "JP": "🇯🇵", "SG": "🇸🇬", "AU": "🇦🇺",
    "HK": "🇭🇰", "TW": "🇹🇼", "KR": "🇰🇷", "IN": "🇮🇳", "BR": "🇧🇷",
    "SE": "🇸🇪", "NO": "🇳🇴", "DK": "🇩🇰", "FI": "🇫🇮", "IT": "🇮🇹",
    "ES": "🇪🇸", "PL": "🇵🇱", "UA": "🇺🇦", "CZ": "🇨🇿", "SK": "🇸🇰",
    "AT": "🇦🇹", "CH": "🇨🇭", "BE": "🇧🇪", "IE": "🇮🇪", "PT": "🇵🇹",
    "GR": "🇬🇷", "HU": "🇭🇺", "RO": "🇷🇴", "BG": "🇧🇬", "TR": "🇹🇷",
    "IL": "🇮🇱", "AE": "🇦🇪", "SA": "🇸🇦", "ZA": "🇿🇦", "AR": "🇦🇷",
    "MX": "🇲🇽", "ID": "🇮🇩", "MY": "🇲🇾", "PH": "🇵🇭", "TH": "🇹🇭",
    "VN": "🇻🇳", "CN": "🇨🇳", "EE": "🇪🇪", "LV": "🇱🇻", "LT": "🇱🇹",
    "IR": "🇮🇷",
}


async def _enrich_countries(
    alive: dict[str, tuple[VlessConfig, ProbeResult]],
    settings: Settings,
) -> None:
    """Resolve countries for all alive servers via ip-api.com batch API."""
    if not alive:
        return

    import aiohttp

    uris_to_resolve: list[tuple[str, VlessConfig]] = []
    seen_ips: set[str] = set()
    for uri, (cfg, _pr) in alive.items():
        ip = cfg.address
        if ip not in seen_ips:
            seen_ips.add(ip)
            uris_to_resolve.append((uri, cfg))

    if not uris_to_resolve:
        return

    log.info("Resolving %d IPs via ip-api.com...", len(uris_to_resolve))
    try:
        async with aiohttp.ClientSession() as session:
            payload = [{"query": cfg.address} for _, cfg in uris_to_resolve]
            async with session.post(
                "http://ip-api.com/batch",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 200:
                    results = await resp.json()
                    for item in results:
                        ip = item.get("query", "")
                        cc = item.get("countryCode", "")
                        country = item.get("country", "")
                        flag = COUNTRY_FLAGS.get(cc, "🌍")
                        for uri, (cfg, pr) in list(alive.items()):
                            if cfg.address == ip:
                                new_remark = f"{flag} {country} {cfg.remark or cfg.address}"
                                cfg.remark = new_remark
                                alive[uri] = (cfg, pr)
                    log.info("GeoIP resolved %d countries", len(results))
    except Exception as exc:
        log.warning("GeoIP failed: %s", exc)


def _write_subscription_files(
    alive: dict[str, tuple[VlessConfig, ProbeResult]],
) -> None:
    """Write configs.txt (all) and best.txt (fastest)."""
    if not alive:
        return

    import pathlib

    out = pathlib.Path("data")
    out.mkdir(parents=True, exist_ok=True)

    # Sort by country then latency
    sorted_items = sorted(
        alive.items(),
        key=lambda x: (x[1][0].remark or "", x[1][1].latency_ms or 9999),
    )

    # Find best (lowest latency)
    best_item = min(alive.items(), key=lambda x: x[1][1].latency_ms or 9999)
    best_uri = best_item[0]

    config_lines: list[str] = []
    for uri, (cfg, pr) in sorted_items:
        lag = f" ⚡{pr.latency_ms:.0f}ms" if pr.latency_ms else ""
        tag = " 🏆BEST" if uri == best_uri else ""
        remark = (cfg.remark or "") + lag + tag
        lines_for_uri = [line for line in cfg.to_uri().split("\n") if line.strip()]
        original = lines_for_uri[0] if lines_for_uri else ""
        # rsplit("#", 1) — последний # это разделитель remark, не путать с # в query
        if "#" in original:
            base = original.rsplit("#", 1)[0]
            modified = f"{base}#{remark}"
        else:
            modified = f"{original}#{remark}"
        config_lines.append(modified)

    (out / "configs.txt").write_text("\n".join(config_lines) + "\n")

    # best.txt — top 10 fastest (dynamic rotation)
    sorted_by_latency = sorted(alive.items(), key=lambda x: x[1][1].latency_ms or 9999)
    best_lines: list[str] = []
    for idx, (uri, (cfg, pr)) in enumerate(sorted_by_latency[:10]):
        tag = " 🏆BEST" if idx == 0 else f" #{idx+1}"
        remark = f"{cfg.remark or ''} ⚡{pr.latency_ms:.0f}ms{tag}"
        raw = cfg.to_uri()
        if "#" in raw:
            base = raw.rsplit("#", 1)[0]
            best_lines.append(f"{base}#{remark}")
        else:
            best_lines.append(f"{raw}#{remark}")
    (out / "best.txt").write_text("\n".join(best_lines) + "\n")

    best_latency = sorted_by_latency[0][1][1].latency_ms if sorted_by_latency else 0
    _write_singbox_json(alive, out, best_lines)

    log.info("Written %d configs + best.txt (%.0fms)", len(config_lines), best_latency or 0)


def _write_singbox_json(
    alive: dict[str, tuple[VlessConfig, ProbeResult]],
    out: pathlib.Path,
    best_uris: list[str],
) -> None:
    """Generate Sing-box JSON subscription with url-test auto-select."""
    tags: list[str] = []
    outbounds_list: list[dict] = []

    sorted_cfgs = sorted(alive.items(), key=lambda x: x[1][1].latency_ms or 9999)
    for idx, (uri, (cfg, pr)) in enumerate(sorted_cfgs):
        tag = f"V{idx+1:02d}"
        tags.append(tag)

        ob: dict = {
            "type": "vless",
            "tag": tag,
            "server": cfg.address,
            "server_port": cfg.port,
            "uuid": cfg.uuid,
            "flow": cfg.stream.flow or "",
        }

        # TLS
        if cfg.stream.security == SecurityType.TLS:
            tls: dict = {"enabled": True, "insecure": True}
            if cfg.stream.sni:
                tls["server_name"] = cfg.stream.sni
            if cfg.stream.fingerprint:
                tls["fingerprint"] = cfg.stream.fingerprint
            ob["tls"] = tls

        # Transport
        transport: dict = {"type": cfg.stream.network.value}
        if cfg.stream.network == StreamNetwork.WS:
            ws: dict = {}
            if cfg.stream.ws_path:
                ws["path"] = cfg.stream.ws_path
            if cfg.stream.ws_host:
                ws["headers"] = {"Host": cfg.stream.ws_host}
            transport["ws"] = ws
        elif cfg.stream.network == StreamNetwork.GRPC:
            grpc: dict = {}
            if cfg.stream.grpc_service_name:
                grpc["service_name"] = cfg.stream.grpc_service_name
            transport["grpc"] = grpc

        if transport.get(cfg.stream.network.value) or transport["type"] != "tcp":
            ob["transport"] = transport

        outbounds_list.append(ob)

    # url-test outbound (auto best)
    outbounds_list.append({
        "type": "urltest",
        "tag": "🇺🇳 Best",
        "outbounds": tags,
        "url": "http://www.gstatic.com/generate_204",
        "interval": "1m",
    })

    sub_data = {"version": 2, "outbounds": outbounds_list}
    (out / "sub.json").write_text(json.dumps(sub_data, indent=2, ensure_ascii=False))


def _build_state() -> dict:
    return {"sources_checked": {}, "inbounds": {}, "last_run": None}


async def run_collect(settings: Settings) -> RunResult:
    """
    One full collection cycle:
      1. Fetch configs from sources
      2. Parse VLESS URIs
      3. Probe servers
      4. Publish alive ones via backend(s)
    """
    result = RunResult()

    # --- 1. Fetch ---
    log.info("Fetching from %d source(s)...", len(settings.source_urls))
    configs, fetch_errors = await fetch_configs(
        settings.source_urls,
        concurrency=min(len(settings.source_urls) or 1, 5),
    )
    result.errors.extend(fetch_errors)
    result.total = len(configs)
    log.info("Fetched %d config(s), %d error(s)", result.total, len(fetch_errors))
    for err in fetch_errors:
        log.warning("  Fetch error: %s", err)

    if not configs:
        return result

    # Random sample if probe_sample > 0
    sample = configs
    if settings.probe_sample > 0 and len(configs) > settings.probe_sample:
        sample = random.sample(configs, settings.probe_sample)
    log.info("Probing %d server(s) (random sample of %d)...", len(sample), settings.probe_sample)

    # --- 2. Probe (with global timeout) ---
    try:
        probe_results = await asyncio.wait_for(
            probe_all(sample, timeout=settings.probe_timeout, concurrency=settings.probe_concurrency),
            timeout=max(settings.probe_timeout * (len(sample) // settings.probe_concurrency + 1) * 3, 60),
        )
    except (asyncio.TimeoutError, TimeoutError):
        log.error("Probe all timed out")
        return result

    alive: dict[str, tuple[VlessConfig, ProbeResult]] = {}
    for cfg in sample:
        uri = cfg.to_uri()
        pr = probe_results.get(uri)
        if pr is None:
            result.dead += 1
            continue
        if pr.alive:
            alive[uri] = (cfg, pr)
            result.alive += 1
        else:
            result.dead += 1

    log.info("Alive: %d, Dead: %d", result.alive, result.dead)

    # Filter out slow servers (>1000ms ping)
    before = result.alive
    alive = {k: v for k, v in alive.items() if (v[1].latency_ms or 0) <= 1000}
    result.alive = len(alive)
    if before != result.alive:
        log.info("Filtered %d slow servers (ping >1000ms)", before - result.alive)

    if not alive:
        log.warning("No alive servers found, nothing to publish.")
        return result

    # --- 2b. GeoIP + subscription files ---
    await _enrich_countries(alive, settings)
    _write_subscription_files(alive)

    # --- 3. Publish to backend ---
    backend = await create_backend(settings)
    try:
        await backend.initialize()
        state = _build_state()
        result.pushed = await backend.publish(alive, state)
        log.info("Published %d config(s) via backend '%s'", result.pushed, settings.backend)
    finally:
        await backend.cleanup()

    return result
