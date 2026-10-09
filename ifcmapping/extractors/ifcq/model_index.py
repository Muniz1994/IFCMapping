"""What an IFC model contains, collected once when it is opened.

Used for autocompletion, model-aware warnings and the compact text summary
the assistant gets instead of the model itself.
"""
from __future__ import annotations

import difflib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from functools import lru_cache

import ifcopenshell
import ifcopenshell.util.unit as ifc_unit
import ifcquery
from ifcquery import schema as ifc_schema
from ifcquery.ifc_access import is_number, predefined_type

MAX_DISTINCT = 25  # distinct text values kept per property

_QUANTITY_KINDS = {
    "IfcQuantityLength": ("length", "IFCLENGTHMEASURE"),
    "IfcQuantityArea": ("area", "IFCAREAMEASURE"),
    "IfcQuantityVolume": ("volume", "IFCVOLUMEMEASURE"),
    "IfcQuantityCount": ("count", "IFCCOUNTMEASURE"),
    "IfcQuantityWeight": ("weight", "IFCMASSMEASURE"),
    "IfcQuantityTime": ("time", "IFCTIMEMEASURE"),
    "IfcQuantityNumber": ("number", "IFCREAL"),
}


@lru_cache(maxsize=None)
def ancestors(schema: str, ifc_class: str) -> frozenset[str]:
    """Lower-case names of the class and all its supertypes."""
    decl = ifc_schema.entity(schema, ifc_class)
    names = set()
    while decl is not None:
        names.add(decl.name().lower())
        decl = decl.supertype()
    return frozenset(names)


def is_subtype(schema: str, ifc_class: str, of: str) -> bool:
    return of.lower() in ancestors(schema, ifc_class)


@dataclass
class PropInfo:
    kind: str = ""                 # "area" for quantities, else the value's IFC type, e.g. "IfcLabel"
    data_type: str = ""            # IDS dataType, e.g. "IFCAREAMEASURE"
    count: int = 0                 # elements that carry it
    values: Counter = field(default_factory=Counter)  # distinct text/bool values (capped)
    more_values: bool = False
    low: float | None = None
    high: float | None = None

    def add(self, value, n: int) -> None:
        self.count += n
        if value is None:
            return
        if is_number(value):
            self.low = value if self.low is None else min(self.low, value)
            self.high = value if self.high is None else max(self.high, value)
        elif value in self.values or len(self.values) < MAX_DISTINCT:
            self.values[value] += n
        else:
            self.more_values = True

    def summary(self, max_values: int = 5) -> str:
        parts = [self.kind or "?"]
        if self.low is not None:
            parts.append(_num(self.low) if self.low == self.high else f"{_num(self.low)}..{_num(self.high)}")
        if self.values:
            shown = [_short(v) for v, _ in self.values.most_common(max_values)]
            extra = len(self.values) - len(shown)
            parts.append(", ".join(shown) + (f" +{extra}{'+' if self.more_values else ''} more" if extra or self.more_values else ""))
        return " ".join(parts)


def _num(x: float) -> str:
    return f"{x:.6g}"


def _short(v, n: int = 30) -> str:
    if isinstance(v, bool):
        return str(v).lower()
    s = str(v)
    return '"' + (s if len(s) <= n else s[: n - 1] + "…") + '"'


class ModelIndex:
    def __init__(self, model: ifcopenshell.file):
        self.schema = ifcquery.schema_of(model)
        self.class_counts: Counter = Counter()
        self.psets: dict[str, dict[str, PropInfo]] = defaultdict(dict)
        self.pset_classes: dict[str, Counter] = defaultdict(Counter)
        self.predefined: dict[str, Counter] = defaultdict(Counter)  # class -> {"GFA": 3, '"FRACAO"': 2}
        self.names: dict[str, Counter] = defaultdict(Counter)       # spatial class -> Name counts
        try:
            self.length_scale = ifc_unit.calculate_unit_scale(model)
        except Exception:
            self.length_scale = None
        self._build(model)
        self._with_subtypes: Counter | None = None

    # ---- building -------------------------------------------------------------------

    def _build(self, model: ifcopenshell.file) -> None:
        for obj in model.by_type("IfcObject"):
            cls = obj.is_a()
            self.class_counts[cls] += 1
            if hasattr(obj, "PredefinedType"):
                raw, user = predefined_type(obj)
                label = f'"{user}"' if raw == "USERDEFINED" and user else raw
                if label:
                    self.predefined[cls][label] += 1
            if obj.is_a("IfcSpatialStructureElement") and obj.Name:
                names = self.names[cls]
                if obj.Name in names or len(names) < MAX_DISTINCT:
                    names[obj.Name] += 1

        for rel in model.by_type("IfcRelDefinesByProperties"):
            definitions = rel.RelatingPropertyDefinition
            if not isinstance(definitions, (list, tuple)):
                definitions = [definitions]
            classes = Counter(o.is_a() for o in rel.RelatedObjects or ())
            for definition in definitions:
                self._add_definition(definition, classes)

        for rel in model.by_type("IfcRelDefinesByType"):
            classes = Counter(o.is_a() for o in rel.RelatedObjects or ())
            for definition in getattr(rel.RelatingType, "HasPropertySets", None) or ():
                self._add_definition(definition, classes)

    def _add_definition(self, definition, classes: Counter) -> None:
        if definition is None or not getattr(definition, "Name", None):
            return
        n = sum(classes.values())
        name = definition.Name
        props = self.psets[name]
        self.pset_classes[name].update(classes)
        if definition.is_a("IfcPropertySet"):
            for prop in definition.HasProperties or ():
                info = props.setdefault(prop.Name, PropInfo())
                if prop.is_a("IfcPropertySingleValue"):
                    nominal = prop.NominalValue
                    if nominal is not None:
                        info.kind = info.kind or nominal.is_a()
                        info.data_type = info.data_type or nominal.is_a().upper()
                    info.add(nominal.wrappedValue if nominal is not None else None, n)
                elif prop.is_a("IfcPropertyEnumeratedValue"):
                    values = [v.wrappedValue for v in prop.EnumerationValues or ()]
                    info.kind = info.kind or "enumeration"
                    info.add(values[0] if len(values) == 1 else None, n)
                else:
                    info.kind = info.kind or prop.is_a()
                    info.add(None, n)
        elif definition.is_a("IfcElementQuantity"):
            for quantity in definition.Quantities or ():
                kind, data_type = _QUANTITY_KINDS.get(quantity.is_a(), (quantity.is_a(), ""))
                info = props.setdefault(quantity.Name, PropInfo(kind=kind, data_type=data_type))
                value = quantity[3] if len(quantity) > 3 and is_number(quantity[3]) else None
                info.add(value, n)

    # ---- queries --------------------------------------------------------------------------

    def count(self, ifc_class: str) -> int:
        """Elements of a class in the model, subtypes included."""
        if self._with_subtypes is None:
            totals: Counter = Counter()
            for cls, n in self.class_counts.items():
                for name in ancestors(self.schema, cls):
                    totals[name] += n
            self._with_subtypes = totals
        return self._with_subtypes.get(ifc_class.lower(), 0)

    def psets_for(self, ifc_class: str) -> dict[str, int]:
        """Property sets on elements of this class (or its subtypes), with element counts."""
        out = {}
        for pset, classes in self.pset_classes.items():
            n = sum(c for cls, c in classes.items() if is_subtype(self.schema, cls, ifc_class))
            if n:
                out[pset] = n
        return out

    def predefined_for(self, ifc_class: str) -> Counter:
        out: Counter = Counter()
        for cls, values in self.predefined.items():
            if is_subtype(self.schema, cls, ifc_class):
                out.update(values)
        return out

    def suggest_pset(self, name: str) -> str:
        return ifc_schema.suggest(name, self.psets)

    def suggest_property(self, pset: str, name: str) -> str:
        return ifc_schema.suggest(name, self.psets.get(pset, {}))

    def data_types(self) -> dict[str, str]:
        """``{"Pset.Prop": "IFCAREAMEASURE"}`` for every property with a known type."""
        return {f"{pset}.{prop}": info.data_type
                for pset, props in self.psets.items() for prop, info in props.items() if info.data_type}

    # ---- text for the assistant -------------------------------------------------------------

    def _pset_line(self, pset: str) -> str:
        classes = ", ".join(f"{c} {n}" for c, n in self.pset_classes[pset].most_common(4))
        props = "; ".join(f"{p}: {info.summary()}" for p, info in sorted(self.psets[pset].items()))
        return f"{_quote(pset)} [{classes}]: {props}"

    def describe(self, max_chars: int = 12000) -> str:
        lines = [f"Schema {self.schema}."]
        if self.length_scale and self.length_scale != 1:
            lines.append(f"Model length unit = {self.length_scale:g} m. Pset/Qto values below are in model units; "
                         "query results are converted to SI (m, m², m³).")
        lines.append("Elements (class count): " + ", ".join(f"{c} {n}" for c, n in self.class_counts.most_common()))
        if self.predefined:
            lines.append('PredefinedType values ("quoted" = USERDEFINED ObjectType, use as a string):')
            for cls, values in sorted(self.predefined.items()):
                lines.append(f"  {cls}: " + ", ".join(f"{v} {n}" for v, n in values.most_common(15)))
        if self.names:
            lines.append("Spatial element names:")
            for cls, names in sorted(self.names.items()):
                lines.append(f"  {cls}: " + ", ".join(_short(n) for n, _ in names.most_common(15)))
        lines.append("Property sets (Pset [classes]: Property: type values):")
        header = "\n".join(lines)
        out = [header]
        size = len(header)
        psets = sorted(self.psets, key=lambda p: -sum(self.pset_classes[p].values()))
        for i, pset in enumerate(psets):
            line = "  " + self._pset_line(pset)
            if size + len(line) > max_chars:
                out.append(f"  ... {len(psets) - i} more property sets; use search_model to look them up.")
                break
            out.append(line)
            size += len(line) + 1
        return "\n".join(out)

    def search(self, pattern: str, limit: int = 40) -> str:
        """Property-set lines whose set or property names match ``pattern`` (case-insensitive regex or text)."""
        try:
            rx = re.compile(pattern, re.IGNORECASE)
        except re.error:
            rx = re.compile(re.escape(pattern), re.IGNORECASE)
        hits = []
        for pset in sorted(self.psets):
            if rx.search(pset):
                hits.append(self._pset_line(pset))
                continue
            props = {p: i for p, i in self.psets[pset].items() if rx.search(p)}
            if props:
                classes = ", ".join(f"{c} {n}" for c, n in self.pset_classes[pset].most_common(4))
                hits.append(f"{_quote(pset)} [{classes}]: " + "; ".join(f"{p}: {i.summary()}" for p, i in sorted(props.items())))
        for cls, n in self.class_counts.items():
            if rx.search(cls):
                hits.append(f"class {cls}: {n} elements")
        if not hits:
            close = difflib.get_close_matches(pattern, list(self.psets), n=5, cutoff=0.5)
            return "No match." + (f" Similar property sets: {', '.join(close)}" if close else "")
        more = f"\n... {len(hits) - limit} more" if len(hits) > limit else ""
        return "\n".join(hits[:limit]) + more


_IDENT = re.compile(r"^[^\W\d]\w*$")


def _quote(name: str) -> str:
    return name if _IDENT.match(name) else f'"{name}"'
