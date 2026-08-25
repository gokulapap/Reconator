from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Protocol

from app.recon.normalization import NormalizedAsset


@dataclass(frozen=True, slots=True)
class PrioritySignal:
    name: str
    score: float
    reason: str


class PriorityRule(Protocol):
    def evaluate(self, asset: NormalizedAsset, *, is_new: bool) -> list[PrioritySignal]: ...


class NewAssetRule:
    def evaluate(self, asset: NormalizedAsset, *, is_new: bool) -> list[PrioritySignal]:
        if not is_new:
            return []
        return [PrioritySignal("new_asset", 10.0, "first observation of this asset")]


class NamingSignalRule:
    _signals: ClassVar[dict[str, tuple[float, str]]] = {
        "admin": (18.0, "administrative surface"),
        "auth": (16.0, "authentication surface"),
        "login": (16.0, "authentication surface"),
        "api": (14.0, "API surface"),
        "graphql": (16.0, "GraphQL surface"),
        "staging": (15.0, "non-production environment"),
        "stage": (12.0, "non-production environment"),
        "dev": (12.0, "development environment"),
        "internal": (12.0, "internal naming signal"),
        "backup": (14.0, "backup naming signal"),
    }

    def evaluate(self, asset: NormalizedAsset, *, is_new: bool) -> list[PrioritySignal]:
        value = asset.canonical_value.lower()
        return [
            PrioritySignal(f"name:{token}", score, reason)
            for token, (score, reason) in self._signals.items()
            if token in value
        ]


class HTTPStatusRule:
    def evaluate(self, asset: NormalizedAsset, *, is_new: bool) -> list[PrioritySignal]:
        status = asset.attributes.get("status_code")
        if status in {200, 201, 202, 204}:
            return [PrioritySignal("http_success", 6.0, f"HTTP {status} response")]
        if status in {401, 403}:
            return [PrioritySignal("http_auth", 10.0, f"HTTP {status} protected surface")]
        return []


class Prioritizer:
    def __init__(self, rules: list[PriorityRule] | None = None) -> None:
        self.rules = rules or [NewAssetRule(), NamingSignalRule(), HTTPStatusRule()]

    def score(self, asset: NormalizedAsset, *, is_new: bool) -> tuple[float, list[PrioritySignal]]:
        signals = [signal for rule in self.rules for signal in rule.evaluate(asset, is_new=is_new)]
        return sum(signal.score for signal in signals), signals


prioritizer = Prioritizer()
