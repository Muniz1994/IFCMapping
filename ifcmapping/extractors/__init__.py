"""Extractors by key. Add a new source format by registering an extractor here."""
from __future__ import annotations

from .base import Completion, CompletionResult, Diagnostic, Extractor, Row, Source, format_value
from .ifcq import IfcQueryExtractor

__all__ = ["Completion", "CompletionResult", "Diagnostic", "Extractor", "Row", "Source", "format_value",
           "IfcQueryExtractor", "get_extractor"]


def get_extractor(key: str, **options) -> Extractor:
    if key == IfcQueryExtractor.key:
        return IfcQueryExtractor(**options)
    raise ValueError(f"unknown extractor {key!r}")
