"""Glue between the form parameters and IFCQuery: validation, evaluation, IDS."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import ifcquery


class ValueShapeError(Exception):
    """The query ran but did not produce a single value."""


@dataclass
class Row:
    nome: str
    query: str
    value: Any = None
    text: str = ""
    status: str = "empty"  # "ok" | "empty" | "error"
    message: str = ""


def describe_error(err: ifcquery.IfcQueryError) -> str:
    where = []
    if getattr(err, "line", None):
        where.append(f"line {err.line}")
    if getattr(err, "column", None):
        where.append(f"col {err.column}")
    message = getattr(err, "message", None) or str(err)
    return f"{', '.join(where)}: {message}" if where else message


def validate(text: str, schema: str) -> str | None:
    """Return None if the query parses and type-checks, else an error message."""
    try:
        ifcquery.parse(text, schema=schema)
    except ifcquery.IfcQueryError as err:
        return describe_error(err)
    return None


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


def evaluate_one(nome: str, query: str, model, decimals: int = 2) -> Row:
    row = Row(nome, query)
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
    return [evaluate_one(nome, q, model, decimals) for nome, q in queries.items()]


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
