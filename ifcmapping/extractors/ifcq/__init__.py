"""IFCQuery over IFC models."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import ifcopenshell
import ifcquery

from ..base import CompletionResult, Diagnostic, Row
from . import completion, engine
from .model_index import ModelIndex

REFERENCE = (Path(__file__).parent / "reference.md").read_text(encoding="utf-8")
SCHEMAS = ("IFC4", "IFC2X3", "IFC4X3_ADD2")


class IfcSource:
    def __init__(self, model: ifcopenshell.file, name: str):
        self.model = model
        self.name = name
        self.schema = ifcquery.schema_of(model)
        self.index = ModelIndex(model)


class IfcQueryExtractor:
    key = "ifcquery"
    name = "IFCQuery"
    source_suffixes = (".ifc",)
    language_help = REFERENCE

    def __init__(self, schema: str = "IFC4"):
        self.schema = schema

    def open(self, data: bytes, name: str) -> IfcSource:
        fd, path = tempfile.mkstemp(suffix=".ifc")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            return IfcSource(ifcopenshell.open(path), name)
        finally:
            os.remove(path)

    def check(self, query: str, source: IfcSource | None = None) -> list[Diagnostic]:
        return engine.check(query, self.schema, source.index if source else None)

    def complete(self, query: str, pos: int, source: IfcSource | None = None) -> CompletionResult | None:
        return completion.complete(query, pos, self.schema, source.index if source else None)

    def evaluate(self, param_id: str, query: str, source: IfcSource, decimals: int = 2) -> Row:
        return engine.evaluate_one(param_id, query, source.model, decimals)

    def describe(self, source: IfcSource, max_chars: int = 12000) -> str:
        return f"Model {source.name}. " + source.index.describe(max_chars)

    def search(self, source: IfcSource, pattern: str) -> str:
        return source.index.search(pattern)

    # ---- IFCQuery-only extras ---------------------------------------------------------

    def build_ids(self, queries: dict[str, str], title: str, data_types: dict[str, str] | None = None):
        return engine.build_ids(queries, self.schema, title, data_types)

    def warm_up(self) -> None:
        completion.warm_up(self.schema)
