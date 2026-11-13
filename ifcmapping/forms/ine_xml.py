"""INE upload forms (e.g. EdificacaoEDemolicao.xml).

Each ``<v nome="...">`` element in ``<dados>`` holds the parameter label in the
template; filling replaces that text with the computed value, or "NA" when there
is none. ``nome`` is the
parameter code ("AISU001"; demolition variants end in "-A"), and its unit comes
from ``UNITS``.
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

EMPTY_VALUE = "NA"  # written for parameters with no value (no query, nothing found, or an error)

# Unit of each parameter code; a "-A" variant has the unit of its base code.
UNITS: dict[str, str] = {
    **{f"AISU{i:03d}": "m²" for i in (1, 2, 3, 4, 5, 6, *range(17, 30))},
    "AISU007": "m³",
    "AISU008": "m",
    "AISU009": "m",
    "AISU036": "fogos/ha",
}

# Codes used before the AISU codes, so older mapping and queries files still load.
LEGACY_CODES: dict[str, str] = {
    "01.m2": "AISU001", "02.m2": "AISU002", "03.m2": "AISU003", "04.m2": "AISU004",
    "05.m2": "AISU005", "06.m2": "AISU006", "07.m3": "AISU007", "08.m": "AISU008",
    "38": "AISU009", "11": "AISU010", "12": "AISU011", "39": "AISU012",
    "13": "AISU013", "14": "AISU014", "15": "AISU015", "16": "AISU016",
    "17.m2": "AISU017", "18.m2": "AISU018", "19.m2": "AISU019", "20.m2": "AISU020",
    "21.m2": "AISU021", "22.m2": "AISU022", "23.m2": "AISU023", "24.m2": "AISU024",
    "25.m2": "AISU025", "26.m2": "AISU026", "27.m2": "AISU027", "28.m2": "AISU028",
    "30.m2": "AISU029", "31": "AISU030", "32": "AISU031", "33": "AISU032",
    "34": "AISU033", "35": "AISU034", "36": "AISU035", "37": "AISU036",
    "40.m2": "AISU001-A", "41.m2": "AISU002-A", "42.m2": "AISU003-A", "43.m3": "AISU007-A",
    "44.m": "AISU008-A", "45.m": "AISU009-A", "46": "AISU010-A", "47": "AISU011-A",
    "48": "AISU012-A",
}


def _unit_of(nome: str) -> str | None:
    base = nome.removesuffix("-A")
    if base in UNITS:
        return UNITS[base]
    _, sep, suffix = nome.partition(".")  # older templates: "01.m2" -> "m2"
    return suffix if sep and suffix else None


class IneXmlForm:
    key = "ine_xml"
    name = "INE XML form"
    template_suffix = ".xml"
    output_suffix = ".xml"
    legacy_ids = LEGACY_CODES

    def parameters(self, template: bytes) -> list[Parameter]:
        root = ET.fromstring(template)
        return [
            Parameter(v.get("nome", ""), (v.text or "").strip(), _unit_of(v.get("nome", "")))
            for v in root.iterfind(_V_PATH)
        ]

    def fill(self, template: bytes, values: dict[str, str]) -> bytes:
        tree = ET.ElementTree(ET.fromstring(template))
        for v in tree.getroot().iterfind(_V_PATH):
            value = values.get(v.get("nome", ""), "")
            v.text = value if value.strip() else EMPTY_VALUE
        out = io.BytesIO()
        tree.write(out, encoding="utf-8", xml_declaration=True, short_empty_elements=False)
        return out.getvalue()

    def output_name(self, template_name: str) -> str:
        return f"{Path(template_name).stem}_preenchido.xml"
