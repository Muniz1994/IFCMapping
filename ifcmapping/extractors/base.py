"""What an extractor (a query language over some source model) has to provide."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class Diagnostic:
    """A problem in a query. ``start``/``end`` are character offsets into the query text."""

    start: int
    end: int
    message: str
    severity: str = "error"  # "error" | "warning" | "info"

    def to_dict(self) -> dict:
        return {"from": self.start, "to": self.end, "message": self.message, "severity": self.severity}


@dataclass
class Completion:
    label: str                 # text inserted (and matched against what was typed)
    type: str = "text"         # CodeMirror icon: class, property, keyword, function, variable, enum, constant, ...
    detail: str = ""
    info: str = ""
    boost: int = 0
    retrigger: bool = False    # reopen completion after inserting (e.g. after "Pset.")

    def to_dict(self) -> dict:
        out = {"label": self.label, "type": self.type}
        if self.detail:
            out["detail"] = self.detail
        if self.info:
            out["info"] = self.info
        if self.boost:
            out["boost"] = self.boost
        if self.retrigger:
            out["retrigger"] = True
        return out


@dataclass
class CompletionResult:
    start: int                       # offset where the replaced word starts
    options: list[Completion] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"from": self.start, "options": [o.to_dict() for o in self.options]}


@dataclass
class Row:
    """The outcome of evaluating one parameter's query."""

    id: str
    query: str
    value: Any = None
    text: str = ""
    status: str = "empty"  # "ok" | "empty" | "error"
    message: str = ""


def format_value(value: Any, decimals: int = 2) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return ""
        rounded = round(float(value), decimals)
        if rounded.is_integer():
            return str(int(rounded))
        return f"{rounded:.{decimals}f}".rstrip("0").rstrip(".")
    return str(value)


class Source(Protocol):
    """An opened source model (e.g. an IFC file) plus whatever the extractor indexed from it."""

    name: str


class Extractor(Protocol):
    key: str
    name: str
    source_suffixes: tuple[str, ...]  # e.g. (".ifc",)
    language_help: str                # cheat-sheet (Markdown), also used in the LLM system prompt

    def open(self, data: bytes, name: str) -> Source: ...

    def check(self, query: str, source: Source | None = None) -> list[Diagnostic]:
        """Problems in the query, without running it. With a source, also model-aware warnings."""
        ...

    def complete(self, query: str, pos: int, source: Source | None = None) -> CompletionResult | None: ...

    def evaluate(self, param_id: str, query: str, source: Source, decimals: int = 2) -> Row: ...

    def describe(self, source: Source, max_chars: int = 12000) -> str:
        """A compact text summary of the source, for an LLM."""
        ...
