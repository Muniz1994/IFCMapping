"""INE upload forms (e.g. EdificacaoEDemolicao.xml).

Each ``<v nome="...">`` element in ``<dados>`` holds the parameter label in the
template; filling replaces that text with the computed value. A suffix after
the first dot of ``nome`` is the unit ("01.m2" -> "m2").
"""
from __future__ import annotations

import io
import xml.etree.ElementTree as ET
from pathlib import Path

from ..mapping import Parameter

NS = "http://ine.pt/public/xsd/forms"
XSI = "http://www.w3.org/2001/XMLSchema-instance"

ET.register_namespace("", NS)
ET.register_namespace("xsi", XSI)

_V_PATH = f".//{{{NS}}}dados/{{{NS}}}v"


def _unit_of(nome: str) -> str | None:
    _, sep, suffix = nome.partition(".")
    return suffix if sep and suffix else None


class IneXmlForm:
    key = "ine_xml"
    name = "INE XML form"
    template_suffix = ".xml"
    output_suffix = ".xml"

    def parameters(self, template: bytes) -> list[Parameter]:
        root = ET.fromstring(template)
        return [
            Parameter(v.get("nome", ""), (v.text or "").strip(), _unit_of(v.get("nome", "")))
            for v in root.iterfind(_V_PATH)
        ]

    def fill(self, template: bytes, values: dict[str, str]) -> bytes:
        tree = ET.ElementTree(ET.fromstring(template))
        for v in tree.getroot().iterfind(_V_PATH):
            v.text = values.get(v.get("nome", ""), "")
        out = io.BytesIO()
        tree.write(out, encoding="utf-8", xml_declaration=True, short_empty_elements=False)
        return out.getvalue()

    def output_name(self, template_name: str) -> str:
        return f"{Path(template_name).stem}_preenchido.xml"
