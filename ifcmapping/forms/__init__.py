"""Form adapters by key. Add a new form type by registering an adapter here."""
from __future__ import annotations

from .base import FormAdapter
from .ine_xml import IneXmlForm

FORMS: dict[str, FormAdapter] = {f.key: f for f in (IneXmlForm(),)}


def get_form(key: str) -> FormAdapter:
    try:
        return FORMS[key]
    except KeyError:
        raise ValueError(f"unknown form type {key!r}; known: {', '.join(FORMS)}") from None
