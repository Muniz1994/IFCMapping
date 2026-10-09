"""Read and fill the INE form template (EdificacaoEDemolicao.xml).

Each ``<v nome="...">`` element in ``<dados>`` holds the parameter label in the
template; filling replaces that text with the computed value.
"""
from __future__ import annotations

import io
import xml.etree.ElementTree as ET
from dataclasses import dataclass

NS = "http://ine.pt/public/xsd/forms"
XSI = "http://www.w3.org/2001/XMLSchema-instance"

ET.register_namespace("", NS)
ET.register_namespace("xsi", XSI)

_V_PATH = f".//{{{NS}}}dados/{{{NS}}}v"


@dataclass(frozen=True)
class Parameter:
    nome: str
    label: str
    unit: str | None

    @property
    def title(self) -> str:
        unit = f" [{self.unit}]" if self.unit else ""
        return f"{self.label}{unit}"


def _unit_of(nome: str) -> str | None:
    _, sep, suffix = nome.partition(".")
    return suffix if sep and suffix else None


def load_parameters(xml_bytes: bytes) -> list[Parameter]:
    """Return the form parameters in document order."""
    root = ET.fromstring(xml_bytes)
    return [
        Parameter(v.get("nome", ""), (v.text or "").strip(), _unit_of(v.get("nome", "")))
        for v in root.iterfind(_V_PATH)
    ]


def fill_xml(xml_bytes: bytes, values: dict[str, str]) -> bytes:
    """Return the template with every ``<v>`` text replaced by ``values[nome]``.

    Parameters missing from ``values`` are written empty.
    """
    tree = ET.ElementTree(ET.fromstring(xml_bytes))
    for v in tree.getroot().iterfind(_V_PATH):
        v.text = values.get(v.get("nome", ""), "")
    out = io.BytesIO()
    tree.write(out, encoding="utf-8", xml_declaration=True, short_empty_elements=False)
    return out.getvalue()
