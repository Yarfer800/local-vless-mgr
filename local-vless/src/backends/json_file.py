from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from ..models import VlessConfig, ProbeResult
from . import Backend


class JsonBackend(Backend):
    """Write alive configs to a JSON file."""

    def __init__(self, file_path: str = "data/alive.json") -> None:
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
        records: list[dict] = []
        for uri, (cfg, probe) in alive.items():
            records.append({
                "uri": uri,
                "uuid": cfg.uuid,
                "address": cfg.address,
                "port": cfg.port,
                "alive": probe.alive,
                "latency_ms": probe.latency_ms,
                "remark": cfg.remark,
                "stream": {
                    "network": cfg.stream.network.value,
                    "security": cfg.stream.security.value,
                    "sni": cfg.stream.sni,
                },
            })

        data = {
            "count": len(records),
            "updated_at": __import__("datetime").datetime.now().isoformat(),
            "servers": records,
        }

        self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        return len(records)
