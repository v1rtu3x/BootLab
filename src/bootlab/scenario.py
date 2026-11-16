"""Scenario schema and validated configuration objects."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)


VALID_CARGO_FEATURES = {
    "sig-rsa",
    "sig-rsa3072",
    "sig-ecdsa",
    "sig-ecdsa-mbedtls",
    "sig-ecdsa-psa",
    "sig-p384",
    "sig-ed25519",
    "sig-second-key",
    "overwrite-only",
    "swap-offset",
    "swap-move",
    "validate-primary-slot",
    "enc-rsa",
    "enc-aes256-rsa",
    "enc-kw",
    "enc-aes256-kw",
    "enc-ec256",
    "enc-ec256-mbedtls",
    "enc-aes256-ec256",
    "enc-x25519",
    "enc-aes256-x25519",
    "bootstrap",
    "multiimage",
    "ram-load",
    "direct-xip",
    "downgrade-prevention",
    "max-align-16",
    "max-align-32",
    "hw-rollback-protection",
    "check-load-addr",
    "custom-crypto",
    "custom-enc-crypto",
    "logical-sectors",
    "logical-sectors-4k",
    "logical-sectors-128k",
}
ALGORITHM_FEATURE = {
    "ecdsa-p256": "sig-ecdsa",
    "ecdsa-p384": "sig-p384",
    "rsa-2048": "sig-rsa",
    "rsa-3072": "sig-rsa3072",
    "ed25519": "sig-ed25519",
}
VALID_PROFILE_FEATURES = VALID_CARGO_FEATURES | {"swap-scratch"}


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
            Backend.MCUBOOT_SIM: {
                "cargo_test",
                "cargo_features",
                "env",
                "primary_image",
                "candidate_image",
                "expected_selection",
                "key_type",
            },
            Backend.IMGTOOL_VERIFY: {"image", "key_path", "key_id", "key_type"},
        }[self.backend]
        unknown = set(self.backend_args) - allowed
        if unknown:
            raise ValueError(
                f"unsupported backend_args field(s): {', '.join(sorted(unknown))}"
            )
        if (
            self.backend == Backend.MCUBOOT_SIM
            and self.backend_args.get("cargo_test", self.name) == ""
        ):
            raise ValueError("mcuboot_sim backend requires a non-empty cargo_test name")
        if self.backend == Backend.MCUBOOT_SIM:
            test_name = self.backend_args.get("cargo_test", self.name)
            features = self.backend_args.get("cargo_features", "sig-ecdsa")
            env = self.backend_args.get("env", {})
            if not isinstance(test_name, str) or not test_name.strip():
                raise ValueError("cargo_test must be a non-empty string")
            if not isinstance(features, str):
                raise ValueError("cargo_features must be a string")
            tokens = features.split()
            unknown = set(tokens) - VALID_CARGO_FEATURES
            if unknown:
                raise ValueError(
                    f"unsupported Cargo feature(s): {', '.join(sorted(unknown))}"
                )
            if len(tokens) != len(set(tokens)):
                raise ValueError("cargo_features must not repeat a feature")
            direct = test_name == "bootlab_direct_image"
            direct_fields = {
                "primary_image",
                "candidate_image",
                "expected_selection",
                "key_type",
            }
            if direct and not {
                "primary_image",
                "candidate_image",
                "expected_selection",
            }.issubset(self.backend_args):
                raise ValueError(
                    "bootlab_direct_image requires primary_image, candidate_image, and expected_selection"
                )
            if not direct and direct_fields.intersection(self.backend_args):
                raise ValueError(
                    "direct image arguments require cargo_test: bootlab_direct_image"
                )
            if direct:
                for key in ("primary_image", "candidate_image", "expected_selection"):
                    if (
                        not isinstance(self.backend_args.get(key), str)
                        or not self.backend_args[key].strip()
                    ):
                        raise ValueError(f"{key} must be a non-empty string")
                if self.backend_args["expected_selection"] not in {
                    "candidate",
                    "primary",
                }:
                    raise ValueError("expected_selection must be candidate or primary")
                if self.primary is None or self.secondary is None:
                    raise ValueError(
                        "direct image scenarios require declared primary and secondary images"
                    )
                if self.primary.version is None or self.secondary.version is None:
                    raise ValueError(
                        "direct image scenarios require declared image versions"
                    )
                if self.primary.trusted is None or self.secondary.trusted is None:
                    raise ValueError(
                        "direct image scenarios require declared trust expectations for both images"
                    )
                selected_ref = (
                    self.secondary
                    if self.backend_args["expected_selection"] == "candidate"
                    else self.primary
                )
                if not selected_ref.trusted:
                    raise ValueError(
                        "direct expected selection must refer to a trusted image"
                    )
                if self.expect.booted_version != selected_ref.version:
                    raise ValueError(
                        "expect.booted_version must match the expected direct image selection"
                    )
                key_type = self.backend_args.get("key_type", "ecdsa-p256")
                if key_type not in ALGORITHM_FEATURE:
                    raise ValueError("unsupported direct image key_type")
                if ALGORITHM_FEATURE[key_type] not in tokens:
                    raise ValueError(
                        "direct image key_type must match an enabled Cargo signature feature"
                    )
                if "BOOTLAB_FAULT_INDEX" in env:
                    try:
                        direct_fault = int(env["BOOTLAB_FAULT_INDEX"])
                    except (TypeError, ValueError) as exc:
                        raise ValueError(
                            "env.BOOTLAB_FAULT_INDEX must be an integer"
                        ) from exc
                    if (
                        direct_fault < 0
                        or self.fault.index != direct_fault
                        or self.fault.type != "reset"
                    ):
                        raise ValueError(
                            "fault declaration must match nonnegative env.BOOTLAB_FAULT_INDEX"
                        )
                elif self.category == Category.FAULT:
                    raise ValueError(
                        "direct fault scenarios require env.BOOTLAB_FAULT_INDEX"
                    )
            if not isinstance(env, dict) or any(
                not isinstance(key, str) or not isinstance(value, str)
                for key, value in env.items()
            ):
                raise ValueError("env must map string keys to string values")
            if self.category == Category.FAULT and test_name != "bootlab_direct_image":
                try:
                    env_index = int(env["FAULT_INDEX"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError(
                        "fault scenarios require integer env.FAULT_INDEX"
                    ) from exc
                if self.fault.index != env_index:
                    raise ValueError("fault.index must match env.FAULT_INDEX")
                if self.fault.type != "reset":
                    raise ValueError(
                        "fault campaigns currently support only type: reset"
                    )
            elif "FAULT_INDEX" in env:
                raise ValueError("env.FAULT_INDEX is only valid for fault scenarios")
        if self.backend == Backend.IMGTOOL_VERIFY and not self.backend_args.get(
            "image"
        ):
            raise ValueError("imgtool_verify backend requires backend_args.image")
        if self.backend == Backend.IMGTOOL_VERIFY:
            for key in ("image", "key_path", "key_id", "key_type"):
                if key in self.backend_args and not isinstance(
                    self.backend_args[key], str
                ):
                    raise ValueError(f"{key} must be a string")
            if "key_type" in self.backend_args and self.backend_args[
                "key_type"
            ] not in {"ecdsa-p256", "ecdsa-p384", "rsa-2048", "rsa-3072", "ed25519"}:
                raise ValueError("unsupported key_type")
        if self.expect.verify_rejected and self.backend != Backend.IMGTOOL_VERIFY:
            raise ValueError(
                "verify_rejected is supported only by imgtool_verify scenarios"
            )
        if self.expect.invalid_image_booted:
            raise ValueError(
                "expect.invalid_image_booted is unsupported by this simulator"
            )
        return self

    @field_validator("expect")
    @classmethod
    def check_outcomes(cls, v: ExpectSpec) -> ExpectSpec:
        allowed = {
            "old_authenticated_image",
            "new_authenticated_image",
            "secure_refusal",
            "infrastructure_error",
            "validator_crash",
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
        return cls(**yaml.safe_load(path.read_text()))

    def to_yaml(self, path: Path) -> None:
        data = self.model_dump(exclude_none=True)
        path.write_text(yaml.safe_dump(_serialize_enums(data), sort_keys=False))


class _ProfileBootloader(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repository: str
    commit: str
    branch: str | None = None
    description: str | None = None

    @field_validator("commit")
    @classmethod
    def valid_commit(cls, value: str) -> str:
        if len(value) != 40 or any(
            char not in "0123456789abcdef" for char in value.lower()
        ):
            raise ValueError(
                "bootloader.commit must be a full 40-character hexadecimal revision"
            )
        return value


class _ProfileSlot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base: int = Field(ge=0)
    size: int = Field(gt=0)


class _ProfileDevice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    align: int
    erased_value: int
    primary_slot: _ProfileSlot
    secondary_slot: _ProfileSlot
    scratch: _ProfileSlot | None = None

    @model_validator(mode="after")
    def valid_layout(self) -> "_ProfileDevice":
        if self.align not in {1, 2, 4, 8, 16, 32}:
            raise ValueError("device.align must be one of 1, 2, 4, 8, 16, 32")
        if self.erased_value not in {0, 255}:
            raise ValueError("device.erased_value must be 0 or 255")
        spans = [self.primary_slot, self.secondary_slot]
        if self.scratch:
            spans.append(self.scratch)
        for index, left in enumerate(spans):
            for right in spans[index + 1 :]:
                if (
                    left.base < right.base + right.size
                    and right.base < left.base + left.size
                ):
                    raise ValueError("device flash regions must not overlap")
        return self


class _ProfileSignature(BaseModel):
    model_config = ConfigDict(extra="forbid")
    algorithm: str
    key_id: str
    trusted_key_ids: list[str] | None = None
    public_key_hash_format: str | None = None


class _ProfileImage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    header_size: int = Field(gt=0)
    slot_size: int = Field(gt=0)
    align: int = Field(gt=0)
    overwrite_only: bool
    downgrade_prevention: bool


class ProfileSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    bootloader: _ProfileBootloader
    device: _ProfileDevice
    signature: _ProfileSignature
    image: _ProfileImage
    security_counter: dict[str, Any] | None = None
    features: list[str]
    notes: str | None = None

    @model_validator(mode="after")
    def validate_effective_configuration(self) -> "ProfileSpec":
        if self.signature.algorithm not in ALGORITHM_FEATURE:
            raise ValueError(
                f"unsupported signature algorithm: {self.signature.algorithm}"
            )
        if (
            self.image.slot_size != self.device.primary_slot.size
            or self.image.slot_size != self.device.secondary_slot.size
        ):
            raise ValueError("image.slot_size must match both configured slot sizes")
        if self.image.align != self.device.align:
            raise ValueError("image.align must match device.align")
        unknown = set(self.features) - VALID_PROFILE_FEATURES
        if unknown:
            raise ValueError(
                f"unsupported profile feature(s): {', '.join(sorted(unknown))}"
            )
        feature_set = set(self.features)
        if ALGORITHM_FEATURE[self.signature.algorithm] not in feature_set:
            raise ValueError(
                "profile features do not enable the declared signature algorithm"
            )
        if ("overwrite-only" in feature_set) != self.image.overwrite_only:
            raise ValueError(
                "profile overwrite-only feature conflicts with image.overwrite_only"
            )
        if ("downgrade-prevention" in feature_set) != self.image.downgrade_prevention:
            raise ValueError(
                "profile downgrade-prevention feature conflicts with image.downgrade_prevention"
            )
        return self


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
    "ProfileSpec",
    "VALID_CARGO_FEATURES",
    "VALID_PROFILE_FEATURES",
    "ALGORITHM_FEATURE",
    "load_scenario",
    "ValidationError",
]
