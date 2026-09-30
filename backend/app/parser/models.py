"""What the LLMs are asked to return. Internal to the parser; mapped onto app.contracts.

Every property is required (nullable where it can be missing) and extra keys are
forbidden, so the schema also works with providers that enforce it strictly.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

LLMForm = Literal[
    "tablet",
    "capsule",
    "syrup",
    "suspension",
    "injection",
    "cream",
    "ointment",
    "gel",
    "drops",
    "inhaler",
    "powder",
    "sachet",
    "other",
]
LLMField = Literal["drug", "strength", "form", "frequency", "duration", "quantity"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RxLine(_Strict):
    raw_text: str = Field(description="The whole medicine line exactly as written, abbreviations kept")
    form_as_written: str | None = Field(description="Prefix as written: 'Tab.', 'Cap', 'Syp', 'Inj'...")
    form: LLMForm | None = Field(description="Dosage form implied by the prefix or name")
    drug: str | None = Field(description="Brand or generic name only, without strength or form")
    strength: str | None = Field(description="Strength exactly as written, e.g. '625', '500 mg', '5ml'")
    frequency: str | None = Field(description="Frequency exactly as written, e.g. '1-0-1', 'BD', 'SOS'")
    duration: str | None = Field(description="Duration exactly as written, e.g. 'x 5 days', '5/7'")
    quantity: int | None = Field(
        description="Explicit count written, in tablets/capsules for solid forms or bottles/tubes/"
        "sachets otherwise, e.g. '#10' -> 10; null if not written or written in strips/packs"
    )
    instructions: str | None = Field(description="e.g. 'after food', 'before breakfast'")
    illegible_fields: list[LLMField] = Field(description="Fields you could not read with confidence")


class RxExtraction(_Strict):
    doctor_name: str | None
    clinic_name: str | None
    patient_name: str | None
    rx_date: str | None = Field(description="Date as written on the prescription")
    lines: list[RxLine] = Field(description="Medicine lines in order, excluding struck-through ones")


class RerankChoice(_Strict):
    choice: int | None = Field(description="1-based number of the matching candidate, or null for none")
    reason: str = Field(description="One short sentence, pharmacist-facing")
