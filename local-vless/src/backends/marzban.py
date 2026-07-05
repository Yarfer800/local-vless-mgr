from __future__ import annotations

import asyncio
import logging
from typing import Optional

import aiohttp

from ..models import VlessConfig, ProbeResult
from . import Backend

log = logging.getLogger(__name__)

VLESS_INBOUND_TAG = "vless-auto"


class MarzbanBackend(Backend):
    """
    Python Marzban integration via User API.

    Auto-enables VLESS protocol in Xray config if missing,
    then creates VLESS users for each alive config.
    """

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        remark_prefix: str = "vls",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._remark_prefix = remark_prefix
        self._session: Optional[aiohttp.ClientSession] = None
        self._token: Optional[str] = None

    async def initialize(self) -> None:
        self._session = aiohttp.ClientSession()
        await self._auth()

    async def cleanup(self) -> None:
        if self._session:
            await self._session.close()

    async def _auth(self) -> None:
        if not self._session:
            raise RuntimeError("Session not initialized")
        resp = await self._session.post(
            f"{self._base_url}/api/admin/token",
            data={"username": self._username, "password": self._password},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        self._token = (await resp.json())["access_token"]
        log.info("Authenticated with Marzban")

    async def _req(self, method: str, path: str, **kwargs) -> dict | list | None:
        """Authenticated request with auto-reauth on 401."""
        url = f"{self._base_url}{path}"
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self._token}"

        for attempt in range(2):
            async with self._session.request(method, url, headers=headers, **kwargs) as resp:
                if resp.status == 204:
                    return None
                if resp.status == 401:
                    await self._auth()
                    headers["Authorization"] = f"Bearer {self._token}"
                    continue
                if resp.status >= 400:
                    body = await resp.json()
                    detail = body.get("detail", body) if isinstance(body, dict) else str(body)
                    log.warning("Marzban %s %s: %s", method, path, detail)
                    return None
                return await resp.json()
        return None

    async def _ensure_vless_enabled(self) -> bool:
        """Add VLESS inbound to Xray config if missing."""
        config = await self._req("GET", "/api/core/config")
        if config is None:
            log.warning("Cannot read Xray config")
            return False

        inbounds = config.get("inbounds", [])
        if isinstance(inbounds, list) and any(i.get("protocol") == "vless" for i in inbounds):
            log.info("VLESS inbound already exists")
            return True

        log.info("VLESS inbound not found — adding...")
        inbounds.append({
            "tag": VLESS_INBOUND_TAG,
            "listen": "0.0.0.0",
            "port": 443,
            "protocol": "vless",
            "settings": {"clients": [], "decryption": "none", "fallbacks": []},
            "streamSettings": {"network": "tcp", "security": "none"},
        })
        if isinstance(config, dict):
            config["inbounds"] = inbounds

        result = await self._req("PUT", "/api/core/config", json=config)
        if result is None:
            log.warning("Failed to update Xray config")
            return False

        log.info("Restarting Xray core...")
        await self._req("POST", "/api/core/restart")
        await asyncio.sleep(3)

        test_ok = await self._try_create_user(
            "_vless_verify", "00000000-0000-0000-0000-000000000000", status="disabled",
        )
        if test_ok:
            await self._req("DELETE", "/api/user/_vless_verify")
            log.info("VLESS protocol enabled successfully")
            return True

        log.warning("VLESS still not available after enabling")
        return False

    async def _try_create_user(self, username: str, uuid: str, status: str = "active") -> bool:
        body = {
            "username": username,
            "proxies": {"vless": {"id": uuid, "flow": ""}},
            "status": status,
            "data_limit": 0,
            "expire": 0,
            "data_limit_reset_strategy": "no_reset",
        }
        result = await self._req("POST", "/api/user", json=body)
        return result is not None

    async def _create_vless_user(
        self, cfg: VlessConfig, username: str
    ) -> tuple[bool, str]:
        """Create a Marzban user. Returns (success, subscription_url)."""
        body = {
            "username": username,
            "proxies": {"vless": {"id": cfg.uuid, "flow": cfg.stream.flow or ""}},
            "data_limit": 0,
            "expire": 0,
            "data_limit_reset_strategy": "no_reset",
            "status": "active",
            "note": f"vless-mgr: {cfg.address}:{cfg.port}",
        }
        result = await self._req("POST", "/api/user", json=body)
        if result and isinstance(result, dict):
            sub_url = result.get("subscription_url", "") or ""
            log.info("User '%s' created (%s:%d)", username, cfg.address, cfg.port)
            return True, sub_url
        return False, ""

    def _sanitize_username(self, address: str, port: int) -> str:
        """Generate valid username: a-z, 0-9, _ (3-32 chars)."""
        import re
        raw = f"{self._remark_prefix}_{address}_{port}"
        name = re.sub(r"[^a-z0-9_]", "_", raw.lower())
        name = re.sub(r"_+", "_", name).strip("_")
        name = name[:32]
        if len(name) < 3:
            name = f"vls_{port}"
        return name

    async def publish(
        self,
        alive: dict[str, tuple[VlessConfig, ProbeResult]],
        state: dict,
    ) -> int:
        vless_ok = await self._ensure_vless_enabled()
        if not vless_ok:
            log.error("Cannot enable VLESS in Marzban — aborting")
            return 0

        pushed = 0
        subs: list[str] = []
        configs: list[str] = []

        for uri, (cfg, _probe) in alive.items():
            username = self._sanitize_username(cfg.address, cfg.port)
            ok, sub_url = await self._create_vless_user(cfg, username)
            if ok:
                pushed += 1
                configs.append(cfg.to_uri())
                if sub_url:
                    subs.append(f"http://localhost:8000{sub_url}")

        import json, pathlib
        out = pathlib.Path("data")
        out.mkdir(parents=True, exist_ok=True)
        (out / "marzban_configs.txt").write_text("\n".join(configs))
        (out / "marzban_subs.txt").write_text("\n".join(subs))

        return pushed
