"""Tools the assistant uses to read the mapping, look up the model and propose queries.

Results are short plain text: the assistant asks for detail when it needs it
instead of getting everything up front.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from ..extractors import Diagnostic, Extractor, Source
from ..mapping import MappingSet


@dataclass
class Proposal:
    param_id: str
    query: str
    explanation: str = ""
    preview: str = ""


@dataclass
class Workspace:
    """What the tools can see and do. The UI owns it and keeps it current."""

    mapping: MappingSet
    extractor: Extractor
    source: Source | None = None
    decimals: int = 2
    on_proposal: Callable[[Proposal], None] = lambda p: None
    proposals: list[Proposal] = field(default_factory=list)


def _schema(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


TOOLS = [
    {
        "name": "list_parameters",
        "description": "List the form parameters: id | label [unit] | status | query on one line. "
                       "Status is ok, empty, or error. Use get_parameters for full details.",
        "input_schema": _schema({
            "filter": {"type": "string", "description": "Case-insensitive text to match in id, label or query."},
            "only_empty": {"type": "boolean", "description": "Only parameters without a query."},
        }, []),
    },
    {
        "name": "get_parameters",
        "description": "Full details of some parameters: label, unit, notes, query, problems and, "
                       "when a model is loaded, the computed value.",
        "input_schema": _schema({"ids": {"type": "array", "items": {"type": "string"}}}, ["ids"]),
    },
    {
        "name": "search_model",
        "description": "Search the loaded model's property sets, properties and classes by name "
                       "(case-insensitive regex). Returns value types and sample values.",
        "input_schema": _schema({"pattern": {"type": "string"}}, ["pattern"]),
    },
    {
        "name": "check_query",
        "description": "Check a query for errors and warnings and, when a model is loaded, run it. "
                       "Use this to test a query before proposing it.",
        "input_schema": _schema({"query": {"type": "string"}}, ["query"]),
    },
    {
        "name": "propose_query",
        "description": "Propose a query for a parameter. The user accepts or rejects it in the app; "
                       "nothing changes until they accept. Rejected if the query has errors.",
        "input_schema": _schema({
            "param_id": {"type": "string"},
            "query": {"type": "string"},
            "explanation": {"type": "string", "description": "One short sentence for the user."},
        }, ["param_id", "query"]),
    },
]
for _tool in TOOLS:
    _tool["eager_input_streaming"] = True  # inputs stream as generated; run_tool validates them


def _one_line(text: str, limit: int = 140) -> str:
    flat = " ⏎ ".join(line.strip() for line in text.strip().splitlines() if line.strip())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _problems(diags: list[Diagnostic]) -> str:
    return "; ".join(f"{d.severity}: {d.message}" for d in diags)


def _status(ws: Workspace, query: str) -> str:
    if not query.strip():
        return "empty"
    return "error" if any(d.severity == "error" for d in ws.extractor.check(query)) else "ok"


def _run(ws: Workspace, query: str) -> str:
    if ws.source is None:
        return "no model loaded"
    row = ws.extractor.evaluate("?", query, ws.source, ws.decimals)
    if row.status == "ok":
        return row.text + (f" ({row.message})" if row.message else "")
    return f"{row.status}: {row.message}"


def list_parameters(ws: Workspace, filter: str = "", only_empty: bool = False) -> str:
    needle = filter.lower()
    lines = []
    for p in ws.mapping.parameters:
        if only_empty and p.query.strip():
            continue
        if needle and needle not in f"{p.id} {p.label} {p.query}".lower():
            continue
        lines.append(f"{p.id} | {p.title} | {_status(ws, p.query)} | {_one_line(p.query) or '-'}")
    return "\n".join(lines) or "No parameters match."


def get_parameters(ws: Workspace, ids: list[str]) -> str:
    blocks = []
    for pid in ids:
        p = ws.mapping.get(pid)
        if p is None:
            blocks.append(f"{pid}: no such parameter")
            continue
        parts = [f"id: {p.id}", f"label: {p.label}", f"unit: {p.unit or '-'}"]
        if p.notes:
            parts.append(f"notes: {p.notes}")
        parts.append("query:\n" + (p.query.strip() or "(empty)"))
        if p.query.strip():
            diags = ws.extractor.check(p.query, ws.source)
            if diags:
                parts.append("problems: " + _problems(diags))
            if ws.source is not None:
                parts.append("value: " + _run(ws, p.query))
        blocks.append("\n".join(parts))
    return "\n\n".join(blocks)


def search_model(ws: Workspace, pattern: str) -> str:
    if ws.source is None:
        return "No model is loaded. Ask the user to load one."
    return ws.extractor.search(ws.source, pattern)


def check_query(ws: Workspace, query: str) -> str:
    diags = ws.extractor.check(query, ws.source)
    out = [_problems(diags) or "no problems"]
    if not any(d.severity == "error" for d in diags) and ws.source is not None:
        out.append("value: " + _run(ws, query))
    return "\n".join(out)


def propose_query(ws: Workspace, param_id: str, query: str, explanation: str = "") -> str:
    if ws.mapping.get(param_id) is None:
        raise ToolError(f"no parameter {param_id!r}; use list_parameters")
    diags = ws.extractor.check(query, ws.source)
    errors = [d for d in diags if d.severity == "error"]
    if errors:
        raise ToolError("not proposed, the query has errors: " + _problems(errors))
    proposal = Proposal(param_id, query.strip(), explanation.strip(),
                        _run(ws, query) if ws.source is not None else "")
    ws.proposals.append(proposal)
    ws.on_proposal(proposal)
    warnings = _problems([d for d in diags if d.severity != "error"])
    return "Proposed; waiting for the user to accept." + (f" Value: {proposal.preview}." if proposal.preview else "") \
        + (f" Notes: {warnings}" if warnings else "")


class ToolError(Exception):
    pass


_FUNCTIONS = {
    "list_parameters": (list_parameters, {"filter": str, "only_empty": bool}, set()),
    "get_parameters": (get_parameters, {"ids": list}, {"ids"}),
    "search_model": (search_model, {"pattern": str}, {"pattern"}),
    "check_query": (check_query, {"query": str}, {"query"}),
    "propose_query": (propose_query, {"param_id": str, "query": str, "explanation": str}, {"param_id", "query"}),
}


def run_tool(ws: Workspace, name: str, args: object) -> tuple[str, bool]:
    """Run a tool call. Returns ``(content, is_error)``; never raises."""
    if name not in _FUNCTIONS:
        return f"unknown tool {name!r}", True
    func, types, required = _FUNCTIONS[name]
    if not isinstance(args, dict):
        return "tool input must be an object", True
    missing = required - args.keys()
    if missing:
        return f"missing arguments: {', '.join(sorted(missing))}", True
    for key, value in args.items():
        if key not in types or not isinstance(value, types[key]):
            return f"invalid argument {key!r}", True
    try:
        return func(ws, **args), False
    except ToolError as err:
        return str(err), True
    except Exception as err:  # a tool bug must not end the conversation
        return f"tool failed: {err}", True
