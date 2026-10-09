"""Checking, evaluating and IDS generation for IFCQuery queries."""
from __future__ import annotations

import dataclasses
import re
from typing import Any

import ifcquery
from ifcquery import ast
from ifcquery import schema as ifc_schema

from ..base import Diagnostic, Row, format_value
from .model_index import ModelIndex

_PATH_TEXT = re.compile(r'(?:"[^"\n]*"|[^\W\d]\w*)(?:\s*\.\s*(?:"[^"\n]*"|[^\W\d]\w*))?')
_WORD = re.compile(r'"[^"\n]*"?|\w+|\S')


class ValueShapeError(Exception):
    """The query ran but did not produce a single value."""


def describe_error(err: ifcquery.IfcQueryError) -> str:
    where = []
    if getattr(err, "line", None):
        where.append(f"line {err.line}")
    if getattr(err, "column", None):
        where.append(f"col {err.column}")
    message = getattr(err, "message", None) or str(err)
    return f"{', '.join(where)}: {message}" if where else message


def validate(text: str, schema: str) -> str | None:
    """None if the query parses and type-checks, else an error message."""
    try:
        ifcquery.parse(text, schema=schema)
    except ifcquery.IfcQueryError as err:
        return describe_error(err)
    return None


# ---- diagnostics ------------------------------------------------------------------------

def offset_of(text: str, line: int | None, column: int | None) -> int:
    if not line:
        return 0
    lines = text.split("\n")
    offset = sum(len(lines[i]) + 1 for i in range(min(line - 1, len(lines))))
    return min(offset + max((column or 1) - 1, 0), len(text))


def _span(text: str, start: int, pattern: re.Pattern = _WORD) -> tuple[int, int]:
    """The word (or path) starting at ``start``; the last character when at the end of the text."""
    if start >= len(text.rstrip()):
        end = len(text.rstrip())
        return max(end - 1, 0), max(end, 1)
    m = pattern.match(text, start)
    return start, (m.end() if m else start + 1)


def _walk(node):
    if dataclasses.is_dataclass(node) and not isinstance(node, type):
        yield node
        for f in dataclasses.fields(node):
            yield from _walk(getattr(node, f.name))
    elif isinstance(node, (tuple, list)):
        for item in node:
            yield from _walk(item)


def check(text: str, schema: str, index: ModelIndex | None = None) -> list[Diagnostic]:
    """Syntax, schema and type errors, plus warnings about the result shape and, with a model, unknown names."""
    if not text.strip():
        return []
    try:
        program = ifcquery.parse(text, schema=schema)
    except ifcquery.IfcQueryError as err:
        start, end = _span(text, offset_of(text, err.line, err.column))
        return [Diagnostic(start, end, err.message)]

    diags: list[Diagnostic] = []
    last = program.statements[-1]
    last_type = program.types[-1] if program.types else None
    start = offset_of(text, getattr(last, "line", 1), getattr(last, "column", 1))
    end = len(text.rstrip())
    if last_type == "value list":
        diags.append(Diagnostic(start, end, "Returns a list of values; the parameter needs one. "
                                            "Wrap it in SUM, FIRST, MAX, ...", "warning"))
    elif last_type == "record list":
        diags.append(Diagnostic(start, end, "Returns records; the parameter needs a single value.", "warning"))
    elif last_type == "element list":
        diags.append(Diagnostic(start, end, "The selected elements are counted.", "info"))

    diags.extend(_quoted_enum_warnings(text, program, schema))
    if index is not None:
        diags.extend(_model_warnings(text, program, index))
    return diags


def _quoted_enum_warnings(text: str, program, schema: str) -> list[Diagnostic]:
    """``PredefinedType = "GFA"`` means USERDEFINED "GFA"; warn when GFA is also an enumeration value."""
    out = []
    for entity in _walk(program.statements):
        if not isinstance(entity, ast.Entity) or entity.condition is None:
            continue
        decl = ifc_schema.entity(schema, entity.ifc_class)
        for node in _walk(entity.condition):
            literals = (node.literal,) if isinstance(node, ast.Comparison) else \
                node.literals if isinstance(node, ast.InList) else ()
            if not literals or not node.path.is_attribute or decl is None:
                continue
            attr = ifc_schema.attribute(decl, node.path.name)
            items = ifc_schema.enum_items(attr) if attr is not None else None
            for lit in literals:
                if lit.kind == "string" and items and str(lit.value).upper() in items and lit.line:
                    start, end = _span(text, offset_of(text, lit.line, lit.column))
                    out.append(Diagnostic(start, end, (
                        f'"{lit.value}" (quoted) matches a USERDEFINED type named {lit.value}. '
                        f"For the enumeration value write {str(lit.value).upper()} without quotes."), "warning"))
    return out


def _model_warnings(text: str, program, index: ModelIndex) -> list[Diagnostic]:
    out = []
    for node in _walk(program.statements):
        if isinstance(node, ast.Entity) and node.line and not index.count(node.ifc_class):
            start, end = _span(text, offset_of(text, node.line, node.column))
            out.append(Diagnostic(start, end, f"The model has no {node.ifc_class} elements.", "warning"))
        elif isinstance(node, ast.Path) and node.pset is not None and node.line:
            start, end = _span(text, offset_of(text, node.line, node.column), _PATH_TEXT)
            if node.pset not in index.psets:
                hint = index.suggest_pset(node.pset)
                out.append(Diagnostic(start, end, f"Property set {node.pset!r} is not in the model.{hint}", "warning"))
            elif node.name not in index.psets[node.pset]:
                hint = index.suggest_property(node.pset, node.name)
                out.append(Diagnostic(start, end, f"{node.pset} has no property {node.name!r} in the model.{hint}",
                                      "warning"))
    return out


# ---- evaluation ---------------------------------------------------------------------------

def result_to_value(results: list) -> tuple[Any, str]:
    """Reduce a query's results to one value, using its last statement."""
    if not results:
        raise ValueShapeError("query produced no result")
    last = results[-1]
    if last.kind in ("scalar", "binding"):
        return last.value, ""
    if last.kind == "values":
        if len(last.value) == 1:
            return last.value[0], ""
        raise ValueShapeError(
            f"query returns {len(last.value)} values; wrap it in SUM, FIRST, MAX, ..."
        )
    if last.kind == "elements":
        return len(last.value), "counted the selected elements"
    raise ValueShapeError(f"query returns a {last.kind}; it must yield a single value")


def evaluate_one(param_id: str, query: str, model, decimals: int = 2) -> Row:
    row = Row(param_id, query)
    if not query.strip():
        return row
    try:
        row.value, row.message = result_to_value(ifcquery.run(query, model))
    except ifcquery.IfcQueryError as err:
        row.status, row.message = "error", describe_error(err)
        return row
    except ValueShapeError as err:
        row.status, row.message = "error", str(err)
        return row
    row.text = format_value(row.value, decimals)
    if row.value is None:
        row.message = row.message or "no value found in the model"
    else:
        row.status = "ok"
    return row


def evaluate_all(queries: dict[str, str], model, decimals: int = 2) -> list[Row]:
    return [evaluate_one(pid, q, model, decimals) for pid, q in queries.items()]


# ---- IDS ------------------------------------------------------------------------------------

def parse_data_types(text: str) -> dict[str, str]:
    """Parse ``PSET.PROP=IFCTYPE`` lines (blank lines and // comments ignored)."""
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.split("//", 1)[0].strip()
        if not line:
            continue
        key, sep, value = line.partition("=")
        if not sep or not key.strip() or not value.strip():
            raise ValueError(f"expected PSET.PROP=TYPE, got: {raw!r}")
        out[key.strip()] = value.strip().upper()
    return out


def build_ids(queries: dict[str, str], schema: str, title: str, data_types: dict[str, str] | None = None):
    """Generate an IDS from every non-empty query (each parsed on its own)."""
    sources = [q for q in queries.values() if q.strip()]
    if not sources:
        raise ValueError("no queries defined")
    result = ifcquery.generate_ids(sources, schema=schema, title=title, data_types=data_types or None)
    if not result.ids.specifications:
        raise ValueError("the queries read no attributes or properties, so the IDS would be empty")
    return result
