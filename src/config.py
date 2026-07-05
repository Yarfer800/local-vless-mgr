from __future__ import annotations

import json

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_file_ignore_empty=True,
    )

    # Sources — direct TXT file URLs with vless:// links
    # Can be set via SOURCES in .env (comma-separated or JSON array)
    # Or set the default right here — no .env needed then
    sources: str = "https://raw.githubusercontent.com/Epodonios/v2ray-configs/refs/heads/main/All_Configs_Sub.txt"

    backend: str = "json"  # json | marzban | all

    # Probing
    probe_timeout: float = 5.0
    probe_concurrency: int = 20
    probe_sample: int = 300  # 0 = all; N = random N servers

    # Marzban
    marzban_url: str = ""
    marzban_username: str = ""
    marzban_password: str = ""

    # Marzban inbound settings
    inbound_port_mode: str = "auto"  # auto | random | sequential
    inbound_remark_prefix: str = "[VLS-MGR]"

    # Monitoring
    interval: int = 3600

    # State
    state_file: str = "data/state.json"

    # Logging
    log_level: str = "INFO"

    @property
    def source_urls(self) -> list[str]:
        """Parse sources string into a list of URLs."""
        v = self.sources.strip()
        if not v:
            return []
        if v.startswith("[") and v.endswith("]"):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return [s.strip() for s in parsed if s.strip()]
            except json.JSONDecodeError:
                pass
        return [s.strip() for s in v.split(",") if s.strip()]
