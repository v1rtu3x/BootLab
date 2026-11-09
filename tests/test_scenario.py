"""Tests for scenario schema validation and YAML round-trips."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from bootlab.scenario import Category, ExpectSpec, Matrix, Scenario, load_scenario


def test_expect_spec_defaults() -> None:
    e = ExpectSpec()
    assert e.invalid_image_booted is False
    assert e.verify_rejected is False
    assert e.outcome_in == []


def test_scenario_load(tmp_path: Path) -> None:
    data = {
        "id": "T01",
        "name": "test-scenario",
        "category": "baseline",
        "profile": "mcuboot_swap_reference",
        "operation": "boot",
        "backend": "mcuboot_sim",
        "backend_args": {"cargo_test": "basic_revert"},
        "expect": {"invalid_image_booted": False},
    }
    path = tmp_path / "t01.yaml"
    path.write_text(yaml.safe_dump(data))
    scenario = load_scenario(path)
    assert scenario.id == "T01"
    assert scenario.category == Category.BASELINE
    assert scenario.expect.invalid_image_booted is False


def test_scenario_invalid_id() -> None:
    with pytest.raises(Exception):
        Scenario(id="bad", name="x", category=Category.BASELINE, profile="p")


def test_matrix_round_trip(tmp_path: Path) -> None:
    matrix = Matrix(
        name="test-matrix",
        description="round-trip test",
        scenarios=[
            Scenario(
                id="T01",
                name="test-scenario",
                category=Category.BASELINE,
                profile="mcuboot_swap_reference",
            )
        ],
    )
    path = tmp_path / "matrix.yaml"
    matrix.to_yaml(path)
    loaded = Matrix.from_yaml(path)
    assert loaded.name == "test-matrix"
    assert len(loaded.scenarios) == 1
    assert loaded.scenarios[0].id == "T01"
