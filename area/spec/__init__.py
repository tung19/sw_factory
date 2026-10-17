"""area.spec — requirement -> validated spec artifact (Flow A / Flow B intake)."""
from area.spec.extract import extract_spec
from area.spec.models import (
    Acceptance,
    AcceptanceCriterion,
    Entity,
    EntityField,
    Feature,
    Spec,
    load_acceptance,
    load_spec,
    validate_cross,
)

__all__ = [
    "extract_spec",
    "Spec",
    "Acceptance",
    "AcceptanceCriterion",
    "Entity",
    "EntityField",
    "Feature",
    "load_spec",
    "load_acceptance",
    "validate_cross",
]
