"""Fake catalog and LLM for parser unit tests (no network, no database)."""

from __future__ import annotations

from typing import Any

from app.contracts import SKU, MatchCandidate, Salt
from app.core.llm import LLMError, LLMResult


def sku(sku_id: str, brand: str, form: str, salts: list[tuple[str, str]], rx: bool = True) -> SKU:
    composition = [Salt(name=n, strength=s) for n, s in salts]
    key = " + ".join(f"{n} {s}" for n, s in sorted(salts))
    return SKU(
        sku_id=sku_id,
        brand_name=brand,
        manufacturer="Test Pharma",
        form=form,  # type: ignore[arg-type]
        pack_size=10,
        pack_label="strip of 10",
        mrp_inr=100.0,
        composition=composition,
        composition_key=key,
        rx_only=rx,
    )


AUGMENTIN_625 = sku(
    "aug625", "Augmentin 625 Duo Tablet", "tablet", [("amoxycillin", "500mg"), ("clavulanic acid", "125mg")]
)
AUGMENTIN_375 = sku(
    "aug375", "Augmentin 375 Tablet", "tablet", [("amoxycillin", "250mg"), ("clavulanic acid", "125mg")]
)
AUGMENTIN_SYP = sku(
    "augsyp",
    "Augmentin Duo Oral Suspension",
    "suspension",
    [("amoxycillin", "400mg"), ("clavulanic acid", "57mg")],
)
PAN_40 = sku("pan40", "Pan 40 Tablet", "tablet", [("pantoprazole", "40mg")])
DOLO_650 = sku("dolo650", "Dolo 650 Tablet", "tablet", [("paracetamol", "650mg")], rx=False)


class FakeCatalog:
    def __init__(self, table: dict[str, list[tuple[SKU, float]]]):
        self.table = table
        self.queries: list[str] = []

    async def search(self, conn: Any, query: str, limit: int = 5) -> list[MatchCandidate]:
        self.queries.append(query)
        rows = self.table.get(query.lower(), [])
        return [MatchCandidate(sku=s, score=score) for s, score in rows][:limit]


class FakeLLM:
    """Returns queued payloads in order; records every call."""

    def __init__(self, *payloads: dict[str, Any] | Exception, cost: float = 0.001):
        self.payloads = list(payloads)
        self.calls: list[dict[str, Any]] = []
        self.cost = cost

    async def complete_json(self, model, messages, schema, **kwargs) -> LLMResult:
        self.calls.append({"model": model, "messages": messages, "schema": schema})
        if not self.payloads:
            raise LLMError("no fake payload left")
        payload = self.payloads.pop(0)
        if isinstance(payload, Exception):
            raise payload
        data = schema.model_validate(payload).model_dump(mode="json")
        return LLMResult(data=data, model=model, latency_ms=42, cost_usd=self.cost)
