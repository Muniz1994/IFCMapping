"""Autocompletion for IFCQuery.

The text before the cursor is fed to IFCQuery's LALR parser, which reports the
terminals it can accept next (class name, path, enumeration, keyword, ...).
The tokens already read tell us the context: which class a ``[filter]`` or
``-> projection`` belongs to and which property set follows a dot. Names come
from the IFC schema, the standard property-set templates and, when a model is
loaded, the model itself.
"""
from __future__ import annotations

import re
from functools import lru_cache

import ifcopenshell
import ifcopenshell.util.pset as ifc_pset
from ifcquery import schema as ifc_schema
from ifcquery.parser import _lark  # IFCQuery's own grammar; no public interactive-parser API yet
from lark import Token
from lark.exceptions import LarkError

from ..base import Completion, CompletionResult
from .model_index import ModelIndex, is_subtype

_W = ifcopenshell.ifcopenshell_wrapper
_IDENT = re.compile(r"^[^\W\d]\w*$")
_WORD_BEFORE = re.compile(r"[^\W\d]\w*$")

COMPARE = {"EQ", "NE", "LT", "LE", "GT", "GE", "APPROX"}
FUNCTIONS = {
    "COUNT": "number of elements, or of non-empty values",
    "SUM": "sum of a value list",
    "AVG": "average of a value list",
    "MIN": "smallest value",
    "MAX": "largest value",
    "FIRST": "first value (or element)",
}
KEYWORDS = {
    "LET": ("let ", "let name = expression"),
    "_NOT": ("not ", ""),
    "_AND": ("and ", ""),
    "_OR": ("or ", ""),
    "_IN": ("in (", 'P in ("a", "b")'),
    "_EXISTS": ("exists(", "exists(Pset.Prop): the value is present"),
    "TRUE": ("true", ""),
    "FALSE": ("false", ""),
}


def quote(name: str) -> str:
    return name if _IDENT.match(name) else '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


def literal(value) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return f"{value:g}" if isinstance(value, float) else str(value)
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _unquote(token: Token) -> str:
    v = str(token)
    return v[1:-1].replace('\\"', '"').replace("\\\\", "\\") if token.type == "STRING" else v


def _is_simple(attr) -> bool:
    """False for attributes that hold entities or lists (ObjectPlacement, Representation, ...)."""
    t = attr.type_of_attribute()
    while isinstance(t, (_W.named_type, _W.type_declaration)):
        t = t.declared_type()
    return not isinstance(t, (_W.entity, _W.aggregation_type))


# ---- standard property-set templates ----------------------------------------------------

def _template_schema(schema: str) -> str:
    s = schema.upper()
    return "IFC4X3" if s.startswith("IFC4X3") else "IFC2X3" if s.startswith("IFC2X3") else "IFC4"


@lru_cache(maxsize=4)
def _templates(schema: str):
    try:
        return ifc_pset.get_template(_template_schema(schema))
    except Exception:
        return None


@lru_cache(maxsize=4096)
def template_psets(schema: str, ifc_class: str) -> dict[str, tuple[tuple[str, str], ...]]:
    """Standard Pset_/Qto_ sets applicable to a class: ``{pset: ((prop, measure type), ...)}``."""
    templates = _templates(schema)
    decl = ifc_schema.entity(schema, ifc_class)
    if templates is None or decl is None:
        return {}
    out = {}
    for t in templates.get_applicable(decl.name()):
        out[t.Name] = tuple((p.Name, _template_type(p)) for p in t.HasPropertyTemplates or ())
    return out


def _template_type(prop) -> str:
    """"IfcLabel" for properties, "area" for quantities (TemplateType Q_AREA)."""
    measure = getattr(prop, "PrimaryMeasureType", None)
    if measure:
        return measure
    kind = getattr(prop, "TemplateType", None) or ""
    return kind[2:].lower() if kind.startswith("Q_") else kind.lower() or "property"


def warm_up(schema: str) -> None:
    """Load the property-set templates ahead of the first completion (it takes ~0.5 s)."""
    template_psets(schema, "IfcSpace")


# ---- the parse state at the cursor ----------------------------------------------------------

class _Context:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.variables: list[str] = []
        self.class_stack: list[str | None] = []   # classes whose [filter] we are inside
        self.projection_class: str | None = None
        last_class = None
        paren = 0
        projection_depth = None
        for i, tok in enumerate(tokens):
            t = tok.type
            if t == "LET" and i + 1 < len(tokens) and tokens[i + 1].type == "NAME":
                self.variables.append(str(tokens[i + 1]))
            if t == "_NL":
                self.class_stack.clear()
                self.projection_class, projection_depth, last_class, paren = None, None, None, 0
            elif t == "IFCCLASS":
                last_class = str(tok)
            elif t == "LSQB":
                self.class_stack.append(last_class)
            elif t == "RSQB":
                if self.class_stack:
                    self.class_stack.pop()
            elif t == "ARROW":
                self.projection_class, projection_depth = last_class, paren
            elif t == "LPAR":
                paren += 1
            elif t == "RPAR":
                paren -= 1
                if projection_depth is not None and paren < projection_depth:
                    self.projection_class = None
            elif t not in ("NAME", "STRING", "DOT", "COMMA") and not self.class_stack:
                self.projection_class = None

    @property
    def path_class(self) -> str | None:
        if self.class_stack:
            return self.class_stack[-1]
        return self.projection_class

    def last(self, n: int = 1) -> Token | None:
        return self.tokens[-n] if len(self.tokens) >= n else None

    def literal_path(self) -> tuple[str | None, str] | None:
        """``(pset, name)`` of the path being compared when the cursor is at a literal."""
        for i in range(len(self.tokens) - 1, -1, -1):
            t = self.tokens[i].type
            if t in COMPARE or t == "_IN":
                if i >= 3 and self.tokens[i - 2].type == "DOT":
                    return _unquote(self.tokens[i - 3]), _unquote(self.tokens[i - 1])
                if i >= 1 and self.tokens[i - 1].type in ("NAME", "STRING"):
                    return None, _unquote(self.tokens[i - 1])
                return None
            if t in ("LSQB", "_AND", "_OR", "_NOT"):
                return None
        return None


def _parse(head: str):
    """(tokens, acceptable terminals) after reading ``head``, or None when ``head`` is invalid."""
    try:
        parser = _lark().parse_interactive(head)
        tokens = parser.exhaust_lexer()
        accepts = parser.accepts()
    except LarkError:
        return None
    current_line = head[head.rfind("\n") + 1:]
    if head.strip() and not current_line.strip() and "_NL" in accepts:
        # The cursor is on a new line after a complete statement: a new statement starts here.
        parser.feed_token(Token("_NL", "\n"))
        tokens.append(Token("_NL", "\n"))
        accepts = parser.accepts()
    return tokens, accepts


def _prefix(before: str) -> str:
    """The partly typed word or quoted name that the completion will replace."""
    line = before[before.rfind("\n") + 1:]
    quotes = [m.start() for m in re.finditer(r'(?<!\\)"', line)]
    if len(quotes) % 2:
        return line[quotes[-1]:]
    m = _WORD_BEFORE.search(line)
    return m.group() if m else ""


def _in_comment(before: str) -> bool:
    line = before[before.rfind("\n") + 1:]
    return "//" in re.sub(r'"(?:[^"\\]|\\.)*"', "", line)


# ---- completion -------------------------------------------------------------------------------

def complete(text: str, pos: int, schema: str, index: ModelIndex | None = None) -> CompletionResult | None:
    before = text[:pos]
    if _in_comment(before):
        return None
    prefix = _prefix(before)
    start = pos - len(prefix)
    parsed = _parse(before[:start])
    if parsed is None:
        return None
    ctx, accepts = _Context(parsed[0]), parsed[1]

    options: list[Completion] = []
    cls = ctx.path_class
    last = ctx.last()
    if cls and last is not None and last.type == "DOT" and ctx.last(2) is not None:
        options += _properties(schema, cls, _unquote(ctx.last(2)), index)
    elif cls and "NAME" in accepts:  # a path starts here (literals never accept NAME)
        options += _path_starts(schema, cls, index)
    elif cls and ("ENUM" in accepts or "STRING" in accepts):
        path = ctx.literal_path()
        if path is not None:
            options += _literals(schema, cls, path, index)
    else:
        if "IFCCLASS" in accepts:
            options += _classes(schema, index)
        if "FUNC" in accepts:
            options += [Completion(f"{name}(", "function", info=doc, retrigger=True) for name, doc in FUNCTIONS.items()]
        if "NAME" in accepts:
            options += [Completion(v, "variable", "let") for v in dict.fromkeys(ctx.variables)]
    for terminal, (label, info) in KEYWORDS.items():
        if terminal in accepts:
            options.append(Completion(label, "keyword", info=info, boost=-1,
                                      retrigger=label.endswith(("(", " "))))
    if prefix.startswith('"'):  # inside a string: only quoted names and values fit
        options = [o for o in options if o.label.startswith('"')]
    if not options:
        return None
    return CompletionResult(start, options)


def _classes(schema: str, index: ModelIndex | None) -> list[Completion]:
    out = []
    for name in ifc_schema._entity_names(schema.upper()):
        n = index.count(name) if index else 0
        out.append(Completion(name, "class", f"{n} in model" if n else "", boost=2 if n else 0))
    return out


def _path_starts(schema: str, cls: str, index: ModelIndex | None) -> list[Completion]:
    decl = ifc_schema.entity(schema, cls)
    out = []
    if decl is not None:
        out += [Completion(a.name(), "property", "attribute", boost=1) for a in decl.all_attributes() if _is_simple(a)]
    seen = set()
    if index is not None:
        for pset, n in sorted(index.psets_for(cls).items()):
            seen.add(pset)
            out.append(Completion(quote(pset) + ".", "namespace", f"{n} in model", boost=3, retrigger=True))
    for pset in template_psets(schema, cls):
        if pset not in seen:
            out.append(Completion(quote(pset) + ".", "namespace", "standard", retrigger=True))
    return out


def _properties(schema: str, cls: str, pset: str, index: ModelIndex | None) -> list[Completion]:
    out = []
    seen = set()
    if index is not None:
        for prop, info in sorted(index.psets.get(pset, {}).items()):
            seen.add(prop)
            out.append(Completion(quote(prop), "property", info.summary(3), boost=2))
    for prop, measure in template_psets(schema, cls).get(pset, ()):
        if prop not in seen:
            out.append(Completion(quote(prop), "property", f"{measure} · standard"))
    return out


def _literals(schema: str, cls: str, path: tuple[str | None, str], index: ModelIndex | None) -> list[Completion]:
    pset, name = path
    out = []
    if pset is None:
        decl = ifc_schema.entity(schema, cls)
        attr = ifc_schema.attribute(decl, name) if decl is not None else None
        in_model = index.predefined_for(cls) if index is not None and name == "PredefinedType" else {}
        if attr is not None:
            for item in ifc_schema.enum_items(attr) or ():
                n = in_model.get(item, 0)
                out.append(Completion(item, "enum", f"{n} in model" if n else "", boost=2 if n else 0))
        for value, n in in_model.items():
            if value.startswith('"'):
                out.append(Completion(value, "constant", f"USERDEFINED · {n} in model", boost=3))
        if index is not None and name == "Name":
            for named_class, names in index.names.items():
                if is_subtype(index.schema, named_class, cls):
                    out += [Completion(literal(v), "constant", f"{c} in model") for v, c in names.most_common(20)]
    elif index is not None:
        info = index.psets.get(pset, {}).get(name)
        if info is not None:
            out += [Completion(literal(v), "constant", f"{c} in model") for v, c in info.values.most_common(20)]
    return out
