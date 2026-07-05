from __future__ import annotations

import urllib.parse
import re
from typing import Optional

from .models import VlessConfig, StreamSettings, StreamNetwork, SecurityType


def parse_vless(uri: str) -> Optional[VlessConfig]:
    """
    Parse a single vless:// URI into a VlessConfig.

    Format:
      vless://<uuid>@<host>:<port>?<query_params>#<remark>

    Supports:
      - type=tcp|ws|kcp|http|quic|grpc
      - security=none|tls|reality
      - sni, fp, pbk, sid
      - path, host, serviceName, mode
      - seed, headerType, flow
      - encryption (ignored for structured output)
    """
    if not uri or not uri.startswith("vless://"):
        return None

    # Remove trailing whitespace / invisible chars
    uri = uri.strip()

    try:
        parsed = urllib.parse.urlparse(uri)
    except Exception:
        return None

    # Extract userinfo (uuid@host:port)
    userinfo = parsed.netloc  # e.g. "uuid@host.com:443"
    if not userinfo or "@" not in userinfo:
        return None

    user_part, host_part = userinfo.rsplit("@", 1)
    uuid = user_part.split(":")[0] if ":" in user_part else user_part

    if ":" in host_part:
        address, port_str = host_part.rsplit(":", 1)
        try:
            port = int(port_str)
        except ValueError:
            return None
    else:
        address = host_part
        port = 443  # default

    # Parse query params
    qs = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)

    def g(key: str, default: str | None = None) -> str | None:
        vals = qs.get(key)
        if vals and vals[0]:
            return vals[0]
        return default

    # Network type
    network_str = g("type", "tcp")
    try:
        network = StreamNetwork(network_str)
    except ValueError:
        network = StreamNetwork.TCP

    # Security
    security_str = g("security", "none")
    try:
        security = SecurityType(security_str)
    except ValueError:
        security = SecurityType.NONE

    # Remark
    remark = urllib.parse.unquote(parsed.fragment) if parsed.fragment else None

    stream = StreamSettings(
        network=network,
        security=security,
        sni=g("sni"),
        fingerprint=g("fp"),
        public_key=g("pbk"),
        short_id=g("sid"),
        ws_path=g("path"),
        ws_host=g("host"),
        grpc_service_name=g("serviceName"),
        grpc_mode=g("mode"),
        kcp_seed=g("seed"),
        kcp_header_type=g("headerType"),
        flow=g("flow"),
        http_host=_parse_list(g("host")),
        http_path=_parse_list(g("path")),
    )

    return VlessConfig(
        uuid=uuid,
        address=address,
        port=port,
        stream=stream,
        remark=remark,
    )


def _parse_list(val: str | None) -> list[str] | None:
    """Some params can be comma-separated lists."""
    if val is None:
        return None
    parts = [v.strip() for v in val.split(",") if v.strip()]
    return parts if parts else None


def parse_line(line: str) -> Optional[VlessConfig]:
    """Parse a single line of text (may contain a vless:// uri)."""
    match = re.search(r"vless://\S+", line)
    if not match:
        return None
    return parse_vless(match.group())


def parse_lines(lines: list[str]) -> list[VlessConfig]:
    """Parse multiple lines, returning only valid configs."""
    result: list[VlessConfig] = []
    for line in lines:
        cfg = parse_line(line)
        if cfg is not None:
            result.append(cfg)
    return result
