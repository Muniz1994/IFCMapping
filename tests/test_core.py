import xml.etree.ElementTree as ET

import pytest
from conftest import TEMPLATE

from ifcmapping.extractors import format_value
from ifcmapping.extractors.ifcq import engine
from ifcmapping.forms import get_form
from ifcmapping.forms.ine_xml import NS
from ifcmapping.mapping import MappingSet, Parameter

FORM = get_form("ine_xml")
XMLNS = {"f": NS}


# --------------------------------------------------------------------------- INE form

def test_load_parameters():
    params = FORM.parameters(TEMPLATE)
    assert len(params) == 45
    assert params[0] == Parameter("AISU001", "SUPERFÍCIE TOTAL DO TERRENO OBJETO DA OPERAÇÃO URBANÍSTICA", "m²")
    by_id = {p.id: p for p in params}
    assert by_id["AISU007"].unit == "m³"
    assert by_id["AISU008"].unit == "m"
    assert by_id["AISU010"].unit is None
    assert by_id["AISU029"].unit == "m²"
    assert by_id["AISU036"].unit == "fogos/ha"
    assert by_id["AISU007-A"].unit == "m³"  # demolition variant: unit of the base code
    assert by_id["AISU012-A"].unit is None
    assert len(by_id) == len(params)  # ids are unique


def test_fill_xml():
    out = FORM.fill(TEMPLATE, {"AISU001": "2000", "AISU012": "Habitação", "AISU003": "", "AISU004": "  "})
    root = ET.fromstring(out)
    values = {v.get("nome"): v.text for v in root.iterfind(".//f:dados/f:v", XMLNS)}
    assert values["AISU001"] == "2000"
    assert values["AISU012"] == "Habitação"
    assert values["AISU002"] == "NA"  # no value given
    assert values["AISU003"] == values["AISU004"] == "NA"  # blank value
    assert root.find("f:header", XMLNS).get("chave") == "046B7652-F415-4EE3-BB0E-33F717F4977C"
    assert root.find(".//f:info/f:i", XMLNS).text == "ANEXO-IC"
    text = out.decode("utf-8")
    assert 'xmlns="http://ine.pt/public/xsd/forms"' in text
    assert 'xsi:schemaLocation="http://ine.pt/public/xsd/forms upload_v1.xsd"' in text
    assert '<v nome="AISU002">NA</v>' in text
    assert "ns0:" not in text


# --------------------------------------------------------------------------- mapping file

def test_mapping_round_trip():
    mapping = MappingSet(parameters=FORM.parameters(TEMPLATE))
    mapping["AISU001"].query = "COUNT(IfcSpace)"
    mapping.add(Parameter("X1", "Custom", "m2", notes="added by hand"), after="AISU001")
    again = MappingSet.from_json(mapping.to_json())
    assert again == mapping
    assert [p.id for p in again.parameters[:2]] == ["AISU001", "X1"]
    with pytest.raises(ValueError):
        again.add(Parameter("X1"))
    again.remove("X1")
    assert again.get("X1") is None


def test_legacy_queries_file():
    mapping = MappingSet.from_dict({"AISU001": "COUNT(IfcSpace)", "AISU010": ""})
    assert mapping.is_legacy_source()
    assert mapping.queries() == {"AISU001": "COUNT(IfcSpace)", "AISU010": ""}


def test_merge_parameters_keeps_queries():
    mapping = MappingSet(parameters=[Parameter("AISU001", "old", "m2", "COUNT(IfcSpace)", "check the lot"),
                                     Parameter("custom")])
    added = mapping.merge_parameters(FORM.parameters(TEMPLATE))
    assert len(added) == 44
    assert mapping["AISU001"].query == "COUNT(IfcSpace)"
    assert mapping["AISU001"].notes == "check the lot"
    assert mapping["AISU001"].label.startswith("SUPERFÍCIE")
    assert mapping.get("custom") is not None


def test_legacy_codes_are_renamed():
    mapping = MappingSet.from_dict({"01.m2": "COUNT(IfcSpace)", "30.m2": "x", "48": "y", "AISU002": "z", "02.m2": "w"})
    renamed = mapping.rename_ids(FORM.legacy_ids)
    assert renamed == ["01.m2", "30.m2", "48"]  # 02.m2 kept: AISU002 already exists
    assert mapping.queries() == {"AISU001": "COUNT(IfcSpace)", "AISU029": "x", "AISU012-A": "y",
                                 "AISU002": "z", "02.m2": "w"}
    template_ids = {p.id for p in FORM.parameters(TEMPLATE)}
    assert set(FORM.legacy_ids.values()) == template_ids


def test_apply_queries_reports_unknown_ids():
    mapping = MappingSet(parameters=[Parameter("a")])
    assert mapping.apply_queries({"a": "COUNT(IfcSpace)", "zz": "x"}) == ["zz"]
    assert mapping["a"].query == "COUNT(IfcSpace)"


# --------------------------------------------------------------------------- formatting

@pytest.mark.parametrize("value, expected", [
    (None, ""), (3, "3"), (3.0, "3"), (2.345, "2.35"), (2.5, "2.5"),
    (0.1 + 0.2, "0.3"), ("Habitação", "Habitação"), (float("nan"), ""), (True, "true"),
])
def test_format_value(value, expected):
    assert format_value(value, 2) == expected


def test_parse_data_types():
    text = "Qto.A = ifcareameasure\n\n// comment\nP.B=IFCLABEL  // trailing"
    assert engine.parse_data_types(text) == {"Qto.A": "IFCAREAMEASURE", "P.B": "IFCLABEL"}
    with pytest.raises(ValueError):
        engine.parse_data_types("nonsense")


# --------------------------------------------------------------------------- against a model

def test_evaluate_all(model):
    queries = {
        "AISU001": "FIRST(IfcSite -> PTMU_Licenciamento.SuperficieTotal)",
        "AISU006": "SUM(IfcSpace -> Qto_SpaceBaseQuantities.GrossFloorArea)",
        "AISU032": "let a = SUM(IfcSpace -> Qto_SpaceBaseQuantities.GrossFloorArea)\n"
              "let t = FIRST(IfcSite -> PTMU_Licenciamento.SuperficieTotal)\n"
              "a / t",
        "AISU012": "FIRST(IfcSite -> PTMU_Licenciamento.Uso)",
        "AISU010": "IfcBuildingStorey",
        "AISU013": "IfcSpace -> Qto_SpaceBaseQuantities.GrossFloorArea",
        "AISU011": "COUNT(IfcSpace[Name = ])",
        "AISU005": 'SUM(IfcSpace[PredefinedType = "FRACAO"] -> Qto_SpaceBaseQuantities.GrossFloorArea)',
        "AISU002": "",
    }
    rows = {r.id: r for r in engine.evaluate_all(queries, model, 2)}
    assert (rows["AISU001"].status, rows["AISU001"].text) == ("ok", "2000")
    assert rows["AISU006"].text == "200.5"
    assert rows["AISU032"].text == "0.1"
    assert rows["AISU012"].text == "Habitação"
    assert rows["AISU010"].text == "1" and rows["AISU010"].message
    assert rows["AISU013"].status == "error" and "SUM" in rows["AISU013"].message
    assert rows["AISU011"].status == "error"
    assert rows["AISU005"].text == "80.5"
    assert rows["AISU002"].status == "empty"


def test_validate():
    assert engine.validate("COUNT(IfcSpace)", "IFC4") is None
    assert engine.validate("COUNT(IfcSpace[name = \"x\"])", "IFC4")


def test_build_ids():
    queries = {
        "a": "SUM(IfcSpace -> Qto_SpaceBaseQuantities.GrossFloorArea)",
        "b": "let x = FIRST(IfcSite -> PTMU_Licenciamento.SuperficieTotal)\nx",
        "c": "let x = COUNT(IfcSpace)\nx",  # same let name in another parameter
        "d": "",
    }
    result = engine.build_ids(queries, "IFC4", "Test", {"PTMU_Licenciamento.SuperficieTotal": "IFCAREAMEASURE"})
    xml = result.to_string()
    assert "GrossFloorArea" in xml and "SuperficieTotal" in xml
    with pytest.raises(ValueError):
        engine.build_ids({"a": " "}, "IFC4", "Empty")
    with pytest.raises(ValueError, match="IDS would be empty"):
        engine.build_ids({"a": "COUNT(IfcSpace)"}, "IFC4", "Nothing required")
