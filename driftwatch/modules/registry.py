"""Module registry: one YAML spec per drift module in driftwatch/modules/specs/.

Each spec fills the four slots of the generic engine (plan §4): get_data, expected_relationship,
drift_test, likely_causes. `load_registry()` validates every file and returns live modules first,
then specified ones, each group sorted by name. The API's GET /registry and the console registry
tab read from here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, field_validator

SPECS_DIR = Path(__file__).parent / "specs"
STATUS_ORDER = {"live": 0, "specified": 1}


class ModuleSpec(BaseModel):
    """One drift module as described in its YAML spec. Unknown keys are rejected."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    title: str
    status: Literal["live", "specified"]
    who_cares: str
    why_it_drifts: str
    get_data: str
    expected_relationship: str
    drift_test: str
    likely_causes: str

    @field_validator(
        "name",
        "title",
        "who_cares",
        "why_it_drifts",
        "get_data",
        "expected_relationship",
        "drift_test",
        "likely_causes",
    )
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be empty")
        return v


def load_spec(path: Path) -> ModuleSpec:
    """Load and validate one spec file. The file stem must equal the spec's name."""
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(  # noqa: TRY004 - bad file content, same error type as the other spec checks
            f"{path.name}: expected a mapping at the top level"
        )
    spec = ModuleSpec.model_validate(data)
    if spec.name != path.stem:
        raise ValueError(f"{path.name}: name '{spec.name}' does not match the file name")
    return spec


def load_registry(specs_dir: Path = SPECS_DIR) -> list[ModuleSpec]:
    """Every spec in specs_dir, validated, live first then specified, by name within each."""
    specs = [load_spec(p) for p in sorted(specs_dir.glob("*.yaml"))]
    if not specs:
        raise ValueError(f"no module specs found in {specs_dir}")
    names = [s.name for s in specs]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise ValueError(f"duplicate module names: {dupes}")
    return sorted(specs, key=lambda s: (STATUS_ORDER[s.status], s.name))
