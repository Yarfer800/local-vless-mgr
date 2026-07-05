from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

from ..models import VlessConfig, ProbeResult


class Backend(ABC):
    """Abstract backend for publishing working VLESS configs."""

    @abstractmethod
    async def publish(
        self,
        alive: dict[str, tuple[VlessConfig, ProbeResult]],
        state: dict,
    ) -> int:
        """
        Publish alive configs to the target.

        Returns number of configs successfully published.
        """
        ...

    @abstractmethod
    async def initialize(self) -> None:
        """Any one-time setup (e.g., authenticate to API)."""
        ...

    @abstractmethod
    async def cleanup(self) -> None:
        """Tear down resources."""
        ...
