from __future__ import annotations

import json
from pathlib import Path

from ..models import VlessConfig, ProbeResult
from . import Backend


class XrayOutboundBackend(Backend):
    """
    Generate an Xray config snippet with all alive VLESS servers as outbounds.

    Useful for deploying a standalone Xray instance or merging
    into an existing config.
    """

    def __init__(self, file_path: str = "data/xray_outbounds.json") -> None:
        self._path = Path(file_path)

    async def initialize(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)

    async def cleanup(self) -> None:
        pass

    async def publish(
        self,
        alive: dict[str, tuple[VlessConfig, ProbeResult]],
        state: dict,
    ) -> int:
        outbounds = [
            self._build_outbound(cfg, probe, idx)
            for idx, (uri, (cfg, probe)) in enumerate(alive.items())
        ]

        # Also generate a simple round-robin routing config
        routing = {
            "routing": {
                "domainStrategy": "AsIs",
                "rules": [
                    {
                        "type": "field",
                        "outboundTag": f"vls-mgr-{i}",
                        "domain": ["geosite:netflix", "geosite:youtube"],
                    }
                    for i in range(len(outbounds))
                ],
                "balancers": [],
            },
            "outbounds": outbounds,
        }

        self._path.write_text(
            json.dumps(routing, indent=2, ensure_ascii=False)
        )

        return len(outbounds)

    def _build_outbound(
        self, cfg: VlessConfig, probe: ProbeResult, idx: int
    ) -> dict:
        """Build an Xray outbound JSON block from a working config."""
        settings = {
            "vnext": [
                {
                    "address": cfg.address,
                    "port": cfg.port,
                    "users": [
                        {
                            "id": cfg.uuid,
                            "encryption": "none",
                            "flow": cfg.stream.flow or "",
                        }
                    ],
                }
            ]
        }

        stream = cfg.stream.to_xray_stream()["stream_settings"]

        tag = f"vls-mgr-{idx}"
        remark = cfg.remark or f"{cfg.address}:{cfg.port}"
        latency = probe.latency_ms or 0

        outbound: dict = {
            "tag": tag,
            "protocol": "vless",
            "settings": settings,
            "streamSettings": stream,
            "remark": remark,
            "latency_ms": latency,
        }

        # Add mux settings for better performance
        if cfg.stream.network.value in ("ws", "grpc"):
            outbound["mux"] = {
                "enabled": True,
                "concurrency": 8,
            }

        return outbound
