"""Employee identity helpers: normalized full name only."""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from typing import TypeVar

T = TypeVar("T")


def clean_person_name(value: str | None) -> str:
    """Remove employment annotations that are not part of a person's full name."""
    if not value:
        return ""
    value = unicodedata.normalize("NFKC", value).replace("\u00a0", " ").strip()
    value = re.sub(r"\s*\([^)]*совм[^)]*\)\s*$", "", value, flags=re.IGNORECASE)
    return " ".join(value.split())


def normalize_person_name(value: str | None) -> str:
    value = clean_person_name(value)
    if not value:
        return ""
    value = unicodedata.normalize("NFKC", value).lower().replace("ё", "е")
    return " ".join(re.sub(r"[^а-яa-z0-9]+", " ", value).split())


def build_employee_name_index(employees: Iterable[T]) -> dict[str, T]:
    """Return one canonical employee per normalized name; first occurrence wins."""
    result: dict[str, T] = {}
    for employee in employees:
        key = normalize_person_name(getattr(employee, "full_name", None))
        if key:
            result.setdefault(key, employee)
    return result
