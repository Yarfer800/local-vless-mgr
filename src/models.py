from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class StreamNetwork(str, Enum):
    TCP = "tcp"
    WS = "ws"
    KCP = "kcp"
    HTTP = "http"
    QUIC = "quic"
    GRPC = "grpc"


class SecurityType(str, Enum):
    NONE = "none"
    TLS = "tls"
    REALITY = "reality"


@dataclass
class StreamSettings:
    network: StreamNetwork = StreamNetwork.TCP
    security: SecurityType = SecurityType.NONE
    # TLS / Reality
    sni: Optional[str] = None
    fingerprint: Optional[str] = None
    public_key: Optional[str] = None
    short_id: Optional[str] = None
    # WS
    ws_path: Optional[str] = None
    ws_host: Optional[str] = None
    # gRPC
    grpc_service_name: Optional[str] = None
    grpc_mode: Optional[str] = None  # multi / gun
    # KCP
    kcp_seed: Optional[str] = None
    kcp_header_type: Optional[str] = None
    # HTTP
    http_host: Optional[list[str]] = None
    http_path: Optional[list[str]] = None
    # Sockopt
    flow: Optional[str] = None

    def to_xray_stream(self) -> dict:
        """Convert to Xray streamSettings JSON block."""
        obj: dict = {
            "network": self.network.value,
            "security": self.security.value,
        }

        if self.security == SecurityType.TLS:
            tls: dict = {}
            if self.sni:
                tls["serverName"] = self.sni
            if self.fingerprint:
                tls["fingerprint"] = self.fingerprint
            obj["tlsSettings"] = tls

        if self.security == SecurityType.REALITY:
            reality: dict = {}
            if self.sni:
                reality["serverName"] = self.sni
            if self.fingerprint:
                reality["fingerprint"] = self.fingerprint
            if self.public_key:
                reality["publicKey"] = self.public_key
            if self.short_id:
                reality["shortId"] = self.short_id
            obj["realitySettings"] = reality

        if self.network == StreamNetwork.WS:
            ws: dict = {}
            if self.ws_path:
                ws["path"] = self.ws_path
            ws_headers: dict = {}
            if self.ws_host:
                ws_headers["Host"] = self.ws_host
            if ws_headers:
                ws["headers"] = ws_headers
            obj["wsSettings"] = ws

        if self.network == StreamNetwork.GRPC:
            grpc: dict = {}
            if self.grpc_service_name:
                grpc["serviceName"] = self.grpc_service_name
            if self.grpc_mode:
                grpc["mode"] = self.grpc_mode
            obj["grpcSettings"] = grpc

        if self.network == StreamNetwork.KCP:
            kcp: dict = {}
            if self.kcp_seed:
                kcp["seed"] = self.kcp_seed
            if self.kcp_header_type:
                kcp["header"] = {"type": self.kcp_header_type}
            obj["kcpSettings"] = kcp

        if self.network == StreamNetwork.HTTP:
            http: dict = {}
            if self.http_host:
                http["host"] = self.http_host
            if self.http_path:
                http["path"] = self.http_path
            obj["httpSettings"] = http

        return {"stream_settings": obj}

    def to_marzban_stream_json(self) -> str:
        """Return stream_settings as JSON string for Marzban API."""
        import json
        stream_settings = self.to_xray_stream()["stream_settings"]
        return json.dumps(stream_settings)

    def to_marzban_settings_json(self, uuid: str) -> str:
        """Return settings JSON string for Marzban API (VLESS inbound)."""
        import json
        settings = {
            "clients": [
                {
                    "id": uuid,
                    "flow": self.flow or "",
                    "email": "auto@vless-mgr",
                    "limitIp": 0,
                    "totalGB": 0,
                    "expiryTime": 0,
                    "enable": True,
                    "tgId": "",
                    "subId": "",
                }
            ],
            "decryption": "none",
            "fallbacks": [],
        }
        return json.dumps(settings)


@dataclass
class VlessConfig:
    uuid: str
    address: str
    port: int
    stream: StreamSettings = field(default_factory=StreamSettings)
    remark: Optional[str] = None

    def to_uri(self) -> str:
        """Reconstruct vless:// URI."""
        params: list[str] = []
        if self.stream.network != StreamNetwork.TCP:
            params.append(f"type={self.stream.network.value}")
        if self.stream.security != SecurityType.NONE:
            params.append(f"security={self.stream.security.value}")
        if self.stream.sni:
            params.append(f"sni={self.stream.sni}")
        if self.stream.fingerprint:
            params.append(f"fp={self.stream.fingerprint}")
        if self.stream.public_key:
            params.append(f"pbk={self.stream.public_key}")
        if self.stream.short_id:
            params.append(f"sid={self.stream.short_id}")
        if self.stream.ws_path:
            params.append(f"path={self.stream.ws_path}")
        if self.stream.ws_host:
            params.append(f"host={self.stream.ws_host}")
        if self.stream.grpc_service_name:
            params.append(f"serviceName={self.stream.grpc_service_name}")
        if self.stream.grpc_mode:
            params.append(f"mode={self.stream.grpc_mode}")
        if self.stream.kcp_seed:
            params.append(f"seed={self.stream.kcp_seed}")
        if self.stream.kcp_header_type:
            params.append(f"headerType={self.stream.kcp_header_type}")
        if self.stream.flow:
            params.append(f"flow={self.stream.flow}")

        query = "&".join(params)
        fragment = f"#{self.remark}" if self.remark else ""
        return f"vless://{self.uuid}@{self.address}:{self.port}?{query}{fragment}"


@dataclass
class ProbeResult:
    alive: bool
    latency_ms: Optional[float] = None
    error: Optional[str] = None


@dataclass
class CachedState:
    """Per-config persistent state (last probe, etc.)."""
    uri: str
    last_alive: Optional[bool] = None
    last_latency_ms: Optional[float] = None
    inbound_id: Optional[int] = None  # Marzban inbound ID if created
    inbound_remark: Optional[str] = None


@dataclass
class RunResult:
    """Result of one collection cycle."""
    total: int = 0
    parsed: int = 0
    alive: int = 0
    dead: int = 0
    pushed: int = 0
    errors: list[str] = field(default_factory=list)
