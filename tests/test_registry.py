from pathlib import Path

import pytest
from pydantic import ValidationError

from driftwatch.modules.registry import ModuleSpec, load_registry, load_spec

EXPECTED = {
    "rating_curve",
    "sewer_meter_mass_balance",
    "meter_under_registration",
    "pump_curve",
    "reservoir_stage_storage",
    "well_specific_capacity",
    "model_calibration",
    "rain_gauge_vs_radar",
}
SLOTS = ("get_data", "expected_relationship", "drift_test", "likely_causes")


def test_all_eight_load():
    specs = load_registry()
    assert len(specs) == 8
    assert {s.name for s in specs} == EXPECTED


def test_exactly_one_live_and_it_is_first():
    specs = load_registry()
    live = [s for s in specs if s.status == "live"]
    assert [s.name for s in live] == ["rating_curve"]
    assert specs[0].name == "rating_curve"
    assert all(s.status == "specified" for s in specs[1:])


def test_every_slot_non_empty():
    for s in load_registry():
        for slot in (*SLOTS, "title", "who_cares", "why_it_drifts"):
            assert getattr(s, slot).strip(), f"{s.name}.{slot} is empty"


def test_blank_slot_rejected():
    good = load_registry()[0].model_dump()
    with pytest.raises(ValidationError):
        ModuleSpec.model_validate({**good, "drift_test": "   "})


def test_unknown_status_and_extra_key_rejected():
    good = load_registry()[0].model_dump()
    with pytest.raises(ValidationError):
        ModuleSpec.model_validate({**good, "status": "planned"})
    with pytest.raises(ValidationError):
        ModuleSpec.model_validate({**good, "owner": "someone"})


def test_name_must_match_file(tmp_path: Path):
    good = load_registry()[0].model_dump()
    import yaml

    p = tmp_path / "other_name.yaml"
    p.write_text(yaml.safe_dump(good), encoding="utf-8")
    with pytest.raises(ValueError, match="does not match"):
        load_spec(p)
