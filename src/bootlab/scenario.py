"""Scenario schema and validated configuration objects."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


class Category(str, Enum):
    BASELINE = "baseline"
    TRIAL = "trial"
    INTEGRITY = "integrity"
    AUTHENTICITY = "authenticity"
    VALIDATION = "validation"
    VERSION = "version"
    FAULT = "fault"
    CONFIGURATION = "configuration"


class Operation(str, Enum):
    BOOT = "boot"
    UPGRADE = "upgrade"
    STAGE_THEN_UPGRADE = "stage_then_upgrade"
    TRIAL = "trial"
    CONFIRM = "confirm"


class Backend(str, Enum):
    MCUBOOT_SIM = "mcuboot_sim"
    IMGTOOL_VERIFY = "imgtool_verify"


class FaultSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["reset", "write_error", "erase_error", "none"]
    point: str | None = None
    seed: int | None = None
    index: int | None = None

    @field_validator("index")
    @classmethod
    def nonnegative_index(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("fault index must be >= 0")
        return value


class ImageRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    version: str | None = None
    trusted: bool | None = None


class ExpectSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invalid_image_booted: bool = False
    verify_rejected: bool = False
    outcome_in: list[str] = Field(default_factory=list)
    booted_version: str | None = None
    recovery_boots: int | None = None
    notes: str = ""


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(..., pattern=r"^[A-Z][0-9]{2}[A-Z0-9]*$")
    name: str
    category: Category
    profile: str
    upstream: dict[str, str] | None = None
    primary: ImageRef | None = None
    secondary: ImageRef | None = None
    operation: Operation = Operation.BOOT
    backend: Backend = Backend.MCUBOOT_SIM
    backend_args: dict[str, Any] = Field(default_factory=dict)
    fault: FaultSpec = Field(default_factory=lambda: FaultSpec(type="none"))
    expect: ExpectSpec = Field(default_factory=ExpectSpec)
    mvp: bool = True
    notes: str = ""

    @model_validator(mode="after")
    def validate_backend_args(self) -> "Scenario":
        allowed = {
            Backend.MCUBOOT_SIM: {"cargo_test", "cargo_features", "env"},
            Backend.IMGTOOL_VERIFY: {"image", "key_path", "key_id", "key_type"},
        }[self.backend]
        unknown = set(self.backend_args) - allowed
        if unknown:
            raise ValueError(f"unsupported backend_args field(s): {', '.join(sorted(unknown))}")
        if self.backend == Backend.MCUBOOT_SIM and self.backend_args.get("cargo_test", self.name) == "":
            raise ValueError("mcuboot_sim backend requires a non-empty cargo_test name")
        if self.backend == Backend.IMGTOOL_VERIFY and not self.backend_args.get("image"):
            raise ValueError("imgtool_verify backend requires backend_args.image")
        return self

    @field_validator("expect")
    @classmethod
    def check_outcomes(cls, v: ExpectSpec) -> ExpectSpec:
        allowed = {
            "old_authenticated_image",
            "new_authenticated_image",
            "secure_refusal",
            "infrastructure_error",
        }
        for outcome in v.outcome_in:
            if outcome not in allowed:
                raise ValueError(f"outcome_in contains unsupported value: {outcome}")
        return v


class Matrix(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    description: str
    scenarios: list[Scenario]

    @field_validator("scenarios")
    @classmethod
    def unique_scenario_ids(cls, values: list[Scenario]) -> list[Scenario]:
        ids = [scenario.id for scenario in values]
        duplicates = sorted({case_id for case_id in ids if ids.count(case_id) > 1})
        if duplicates:
            raise ValueError(f"duplicate scenario IDs: {', '.join(duplicates)}")
        return values

    @classmethod
    def from_yaml(cls, path: Path) -> "Matrix":
        data = yaml.safe_load(path.read_text())
        return cls(**data)

    def to_yaml(self, path: Path) -> None:
        data = self.model_dump(exclude_none=True)
        path.write_text(yaml.safe_dump(_serialize_enums(data), sort_keys=False))


def _serialize_enums(obj: Any) -> Any:
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        return {k: _serialize_enums(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize_enums(v) for v in obj]
    return obj


def load_scenario(path: Path) -> Scenario:
    data = yaml.safe_load(path.read_text())
    return Scenario(**data)


__all__ = [
    "Category",
    "Operation",
    "Backend",
    "FaultSpec",
    "ImageRef",
    "ExpectSpec",
    "Scenario",
    "Matrix",
    "load_scenario",
    "ValidationError",
]
