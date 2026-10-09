"""Streamlit app: fill the INE EdificacaoEDemolicao form from an IFC model using IFCQuery.

Run with:  streamlit run app.py
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

import ifcopenshell
import pandas as pd
import streamlit as st

import ine_form
import query_engine
from query_editor import query_editor

HERE = Path(__file__).parent
DEFAULT_TEMPLATE = HERE / "EdificacaoEDemolicao.xml"
QUERIES_FILE = HERE / "queries.json"
SCHEMAS = ["IFC4", "IFC2X3", "IFC4X3"]

CHEATSHEET = """
```
IfcSpace                                       // all spaces (subtypes included)
IfcSpace[Name = "Sala 1"]                      // filter on an attribute
IfcSpace[Pset_X.Prop >= 10]                    // filter on a property: Pset.Property
IfcSpace[PredefinedType = "FRACAO"]            // USERDEFINED type "FRACAO"
IfcBuildingStorey[Name = "Piso 0"] > IfcSpace  // containment
IfcSpace -> Qto_SpaceBaseQuantities.NetFloorArea
COUNT(x)  SUM(x)  AVG(x)  MIN(x)  MAX(x)  FIRST(x)
let a = SUM(IfcSpace -> Qto_SpaceBaseQuantities.GrossFloorArea)
let b = FIRST(IfcSite -> PTMU_Licenciamento.SuperficieTotal)
a / b                                          // last line = value written to the XML
```
- Strings are double-quoted; comments start with `//`.
- `SUM/AVG/MIN/MAX` need values: `SUM(IfcSpace -> Qto.X)`, not `SUM(IfcSpace)`.
- The **last statement** gives the parameter value. A bare element selection is counted.
- Quantities are returned in SI units (m, m², m³).
"""

st.set_page_config(page_title="IFC → INE Edificação e Demolição", layout="wide")


# --------------------------------------------------------------------------- state

def qkey(nome: str) -> str:
    return f"q::{nome}"


def load_saved_queries() -> dict[str, str]:
    if QUERIES_FILE.exists():
        try:
            data = json.loads(QUERIES_FILE.read_text(encoding="utf-8"))
            return {str(k): str(v) for k, v in data.items()}
        except (json.JSONDecodeError, AttributeError):
            st.warning(f"Could not read {QUERIES_FILE.name}; starting with empty queries.")
    return {}


def current_queries(params: list[ine_form.Parameter]) -> dict[str, str]:
    return {p.nome: st.session_state.get(qkey(p.nome), "") for p in params}


def apply_queries(data: dict[str, str]) -> None:
    for nome, text in data.items():
        st.session_state[qkey(nome)] = text
    st.session_state.validation = {}


def on_queries_upload() -> None:
    upload = st.session_state.get("queries_upload")
    if upload is None:
        return
    try:
        data = json.loads(upload.getvalue().decode("utf-8"))
        apply_queries({str(k): str(v) for k, v in data.items()})
        st.session_state.flash = ("success", f"Loaded {len(data)} queries from {upload.name}.")
    except (json.JSONDecodeError, UnicodeDecodeError, AttributeError) as err:
        st.session_state.flash = ("error", f"Invalid queries file: {err}")


if "initialised" not in st.session_state:
    apply_queries(load_saved_queries())
    st.session_state.initialised = True
st.session_state.setdefault("validation", {})


@st.cache_resource(show_spinner="Opening IFC model…")
def open_model(digest: str, _data: bytes):
    fd, path = tempfile.mkstemp(suffix=".ifc")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(_data)
        return ifcopenshell.open(path)
    finally:
        os.remove(path)


# --------------------------------------------------------------------------- sidebar

with st.sidebar:
    st.header("Settings")
    template_upload = st.file_uploader("XML template", type="xml",
                                       help=f"Defaults to {DEFAULT_TEMPLATE.name}")
    if template_upload is not None:
        template_bytes, template_name = template_upload.getvalue(), template_upload.name
    else:
        template_bytes, template_name = DEFAULT_TEMPLATE.read_bytes(), DEFAULT_TEMPLATE.name
    schema = st.selectbox("IFC schema (validation and IDS)", SCHEMAS)
    decimals = st.number_input("Decimal places", min_value=0, max_value=6, value=2)

try:
    params = ine_form.load_parameters(template_bytes)
except Exception as err:  # malformed template
    st.error(f"Could not read the XML template: {err}")
    st.stop()

st.title("IFC → INE Edificação e Demolição")
st.caption(f"Template: {template_name} · {len(params)} parameters")

if flash := st.session_state.pop("flash", None):
    getattr(st, flash[0])(flash[1])

tab_queries, tab_process = st.tabs(["1 · Define queries", "2 · Process IFC & generate XML"])

# --------------------------------------------------------------------------- tab 1

with tab_queries:
    queries = current_queries(params)
    validation: dict[str, tuple[str, str | None]] = st.session_state.validation

    c1, c2, c3, c4 = st.columns(4)
    if c1.button("Validate all", width="stretch"):
        validation.clear()
        for nome, text in queries.items():
            if text.strip():
                validation[nome] = (text, query_engine.validate(text, schema))
        errors = sum(1 for _, err in validation.values() if err)
        if errors:
            st.error(f"{errors} of {len(validation)} queries have errors.")
        else:
            st.success(f"All {len(validation)} queries are valid for {schema}.")
    if c2.button("Save to queries.json", width="stretch"):
        QUERIES_FILE.write_text(json.dumps(queries, ensure_ascii=False, indent=2), encoding="utf-8")
        st.success(f"Saved to {QUERIES_FILE.name}.")
    c3.download_button("Download queries", json.dumps(queries, ensure_ascii=False, indent=2),
                       file_name="queries.json", mime="application/json", width="stretch")
    with c4.popover("Upload queries", width="stretch"):
        st.file_uploader("Queries JSON", type="json", key="queries_upload", on_change=on_queries_upload)

    with st.expander("Query syntax cheat-sheet"):
        st.markdown(CHEATSHEET)

    filled = sum(1 for q in queries.values() if q.strip())
    st.progress(filled / len(params) if params else 0.0,
                text=f"{filled} of {len(params)} parameters have a query")
    st.caption("Edits are applied when you click outside the query box or press Ctrl+Enter.")

    for p in params:
        text = queries[p.nome]
        checked = validation.get(p.nome)
        if checked and checked[0] == text:
            marker = "⚠️ " if checked[1] else "✅ "
        elif text.strip():
            marker = "📝 "
        else:
            marker = ""
        with st.expander(marker + p.title, True):
            query_editor(qkey(p.nome), key=f"editor::{p.nome}",
                         placeholder="e.g. SUM(IfcSpace -> Qto_SpaceBaseQuantities.GrossFloorArea)")
            if checked and checked[0] == text and checked[1]:
                st.error(checked[1])

    st.divider()
    st.subheader("Generate IDS from the queries")
    st.caption("Every attribute and property the queries read becomes an IDS requirement.")
    ids_title = st.text_input("IDS title", value="INE - Edificação e Demolição")
    data_types_text = st.text_area(
        "Property data types (optional, one per line)",
        placeholder="Qto_SpaceBaseQuantities.GrossFloorArea=IFCAREAMEASURE",
        help="PSET.PROP=IFCTYPE. Sets the dataType of property requirements in the IDS.",
    )
    if st.button("Generate IDS", type="primary"):
        try:
            data_types = query_engine.parse_data_types(data_types_text)
            ids_result = query_engine.build_ids(queries, schema, ids_title, data_types)
            st.session_state.ids_xml = ids_result.to_string()
            st.session_state.ids_warnings = list(ids_result.warnings)
        except query_engine.ifcquery.IfcQueryError as err:
            st.session_state.pop("ids_xml", None)
            st.error(f"Query error: {query_engine.describe_error(err)}")
        except ValueError as err:
            st.session_state.pop("ids_xml", None)
            st.error(str(err))
    if "ids_xml" in st.session_state:
        for warning in st.session_state.get("ids_warnings", []):
            st.warning(warning)
        st.download_button("Download IDS", st.session_state.ids_xml, file_name="EdificacaoEDemolicao.ids",
                           mime="application/xml")
        with st.expander("Preview IDS"):
            st.code(st.session_state.ids_xml, language="xml")

# --------------------------------------------------------------------------- tab 2

with tab_process:
    ifc_upload = st.file_uploader("IFC model", type="ifc")
    if ifc_upload is None:
        st.info("Upload an IFC file to run the queries.")
    else:
        data = ifc_upload.getvalue()
        digest = hashlib.sha256(data).hexdigest()
        try:
            model = open_model(digest, data)
        except Exception as err:
            st.error(f"Could not open the IFC file: {err}")
            st.stop()
        st.caption(f"{ifc_upload.name} · schema {model.schema}")
        if model.schema.upper() != schema.upper():
            st.warning(f"The model is {model.schema} but queries are validated against {schema}.")

        if st.button("Run queries", type="primary"):
            with st.spinner("Evaluating queries…"):
                rows = query_engine.evaluate_all(current_queries(params), model, int(decimals))
            st.session_state.run = {"digest": digest, "template": template_bytes, "rows": rows}

        run = st.session_state.get("run")
        if run and run["digest"] == digest and run["template"] == template_bytes:
            rows = run["rows"]
            by_nome = {p.nome: p for p in params}
            icons = {"ok": "✅", "empty": "▫️", "error": "❌"}
            st.dataframe(
                pd.DataFrame([{
                    "": icons[r.status],
                    "Code": r.nome,
                    "Parameter": by_nome[r.nome].label,
                    "Value": r.text,
                    "Unit": by_nome[r.nome].unit or "",
                    "Message": r.message,
                } for r in rows]),
                hide_index=True, width="stretch",
            )
            counts = {s: sum(1 for r in rows if r.status == s) for s in icons}
            st.caption(f"{counts['ok']} filled · {counts['empty']} empty · {counts['error']} errors")

            xml_out = ine_form.fill_xml(template_bytes, {r.nome: r.text for r in rows})
            st.download_button("Download filled XML", xml_out, type="primary",
                               file_name=f"{Path(template_name).stem}_preenchido.xml",
                               mime="application/xml")
            with st.expander("Preview XML"):
                st.code(xml_out.decode("utf-8"), language="xml")
        elif run:
            st.info("Model or template changed. Run the queries again.")
