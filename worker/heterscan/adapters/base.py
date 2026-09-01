from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from ..domain import ApplicationRecord, DiscoveryResult, SearchUnit


class Adapter(ABC):
    name: str
    version = "0.1.0"

    def __init__(self, city_id: str, city_name: str, config: dict) -> None:
        self.city_id = city_id
        self.city_name = city_name
        self.config = config

    def close(self) -> None:
        """Release adapter-owned resources. Stateless adapters need no cleanup."""

    @abstractmethod
    def collect(
        self, unit: SearchUnit, date_from: date, date_to: date
    ) -> list[ApplicationRecord] | DiscoveryResult:
        raise NotImplementedError
