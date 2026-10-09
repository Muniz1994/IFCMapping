"""Parameters to fill and the query that computes each one.

A mapping file is the source of truth for the parameter list: a form template
only seeds it, and parameters can be added or removed afterwards.

    {
      "version": 1,
      "form": "ine_xml",
      "extractor": "ifcquery",
      "parameters": [
        {"id": "01.m2", "label": "SUPERFÍCIE ...", "unit": "m2", "query": "...", "notes": ""}
      ]
    }

A legacy ``queries.json`` (a flat ``{id: query}`` object) is also accepted.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

FORMAT_VERSION = 1


@dataclass
class Parameter:
    id: str
    label: str = ""
    unit: str | None = None
    query: str = ""
    notes: str = ""

    @property
    def title(self) -> str:
        unit = f" [{self.unit}]" if self.unit else ""
        return f"{self.label or self.id}{unit}"


@dataclass
class MappingSet:
    form: str = "ine_xml"
    extractor: str = "ifcquery"
    parameters: list[Parameter] = field(default_factory=list)

    # ---- lookup and editing ----------------------------------------------------

    def get(self, param_id: str) -> Parameter | None:
        return next((p for p in self.parameters if p.id == param_id), None)

    def __getitem__(self, param_id: str) -> Parameter:
        param = self.get(param_id)
        if param is None:
            raise KeyError(param_id)
        return param

    def add(self, param: Parameter, *, after: str | None = None) -> None:
        if not param.id.strip():
            raise ValueError("parameter id is empty")
        if self.get(param.id) is not None:
            raise ValueError(f"parameter {param.id!r} already exists")
        index = len(self.parameters)
        if after is not None:
            index = next((i + 1 for i, p in enumerate(self.parameters) if p.id == after), index)
        self.parameters.insert(index, param)

    def remove(self, param_id: str) -> None:
        self.parameters.remove(self[param_id])

    def queries(self) -> dict[str, str]:
        return {p.id: p.query for p in self.parameters}

    def merge_parameters(self, template_params: list[Parameter]) -> list[str]:
        """Add template parameters that are missing here and refresh labels and units.

        Queries and notes are kept. Returns the ids that were added.
        """
        added = []
        for tp in template_params:
            own = self.get(tp.id)
            if own is None:
                self.parameters.append(Parameter(tp.id, tp.label, tp.unit))
                added.append(tp.id)
            else:
                own.label, own.unit = tp.label or own.label, tp.unit or own.unit
        return added

    def apply_queries(self, queries: dict[str, str]) -> list[str]:
        """Set queries by id. Returns the ids that matched no parameter."""
        unknown = []
        for param_id, query in queries.items():
            param = self.get(str(param_id))
            if param is None:
                unknown.append(str(param_id))
            else:
                param.query = str(query)
        return unknown

    # ---- serialisation ------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "version": FORMAT_VERSION,
            "form": self.form,
            "extractor": self.extractor,
            "parameters": [asdict(p) for p in self.parameters],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def save(self, path: Path) -> None:
        path.write_text(self.to_json() + "\n", encoding="utf-8")

    @classmethod
    def from_dict(cls, data: dict) -> MappingSet:
        if not isinstance(data, dict):
            raise ValueError("a mapping file must contain a JSON object")
        if "parameters" not in data:  # legacy queries.json: {id: query}
            mapping = cls(parameters=[Parameter(str(k)) for k in data])
            mapping.apply_queries({str(k): str(v) for k, v in data.items()})
            return mapping
        params = []
        for raw in data["parameters"]:
            if not isinstance(raw, dict) or not str(raw.get("id", "")).strip():
                raise ValueError(f"invalid parameter entry: {raw!r}")
            params.append(Parameter(
                id=str(raw["id"]),
                label=str(raw.get("label") or ""),
                unit=raw.get("unit") or None,
                query=str(raw.get("query") or ""),
                notes=str(raw.get("notes") or ""),
            ))
        return cls(
            form=str(data.get("form") or "ine_xml"),
            extractor=str(data.get("extractor") or "ifcquery"),
            parameters=params,
        )

    @classmethod
    def from_json(cls, text: str) -> MappingSet:
        return cls.from_dict(json.loads(text))

    @classmethod
    def load(cls, path: Path) -> MappingSet:
        return cls.from_json(path.read_text(encoding="utf-8"))

    def is_legacy_source(self) -> bool:
        """True when loaded from a flat queries file (no labels yet)."""
        return all(not p.label for p in self.parameters)
