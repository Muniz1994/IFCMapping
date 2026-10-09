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
    assert params[0] == Parameter("01.m2", "SUPERFÍCIE TOTAL DO TERRENO OBJETO DA OPERAÇÃO URBANÍSTICA", "m2")
    by_id = {p.id: p for p in params}
    assert by_id["07.m3"].unit == "m3"
    assert by_id["08.m"].unit == "m"
    assert by_id["11"].unit is None
    assert len(by_id) == len(params)  # ids are unique


def test_fill_xml():
    out = FORM.fill(TEMPLATE, {"01.m2": "2000", "39": "Habitação"})
    root = ET.fromstring(out)
    values = {v.get("nome"): v.text for v in root.iterfind(".//f:dados/f:v", XMLNS)}
    assert values["01.m2"] == "2000"
    assert values["39"] == "Habitação"
    assert values["02.m2"] is None  # empty
    assert root.find("f:header", XMLNS).get("chave") == "046B7652-F415-4EE3-BB0E-33F717F4977C"
    assert root.find(".//f:info/f:i", XMLNS).text == "ANEXO-IC"
    text = out.decode("utf-8")
    assert 'xmlns="http://ine.pt/public/xsd/forms"' in text
    assert 'xsi:schemaLocation="http://ine.pt/public/xsd/forms upload_v1.xsd"' in text
    assert '<v nome="02.m2"></v>' in text
    assert "ns0:" not in text


# --------------------------------------------------------------------------- mapping file

def test_mapping_round_trip():
    mapping = MappingSet(parameters=FORM.parameters(TEMPLATE))
    mapping["01.m2"].query = "COUNT(IfcSpace)"
    mapping.add(Parameter("X1", "Custom", "m2", notes="added by hand"), after="01.m2")
    again = MappingSet.from_json(mapping.to_json())
    assert again == mapping
    assert [p.id for p in again.parameters[:2]] == ["01.m2", "X1"]
    with pytest.raises(ValueError):
        again.add(Parameter("X1"))
    again.remove("X1")
    assert again.get("X1") is None


def test_legacy_queries_file():
    mapping = MappingSet.from_dict({"01.m2": "COUNT(IfcSpace)", "11": ""})
    assert mapping.is_legacy_source()
    assert mapping.queries() == {"01.m2": "COUNT(IfcSpace)", "11": ""}


def test_merge_parameters_keeps_queries():
    mapping = MappingSet(parameters=[Parameter("01.m2", "old", "m2", "COUNT(IfcSpace)"), Parameter("custom")])
    added = mapping.merge_parameters(FORM.parameters(TEMPLATE))
    assert len(added) == 44
    assert mapping["01.m2"].query == "COUNT(IfcSpace)"
    assert mapping["01.m2"].label.startswith("SUPERFÍCIE")
    assert mapping.get("custom") is not None


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
        "01.m2": "FIRST(IfcSite -> PTMU_Licenciamento.SuperficieTotal)",
        "06.m2": "SUM(IfcSpace -> Qto_SpaceBaseQuantities.GrossFloorArea)",
        "33": "let a = SUM(IfcSpace -> Qto_SpaceBaseQuantities.GrossFloorArea)\n"
              "let t = FIRST(IfcSite -> PTMU_Licenciamento.SuperficieTotal)\n"
              "a / t",
        "39": "FIRST(IfcSite -> PTMU_Licenciamento.Uso)",
        "11": "IfcBuildingStorey",
        "13": "IfcSpace -> Qto_SpaceBaseQuantities.GrossFloorArea",
        "12": "COUNT(IfcSpace[Name = ])",
        "05.m2": 'SUM(IfcSpace[PredefinedType = "FRACAO"] -> Qto_SpaceBaseQuantities.GrossFloorArea)',
        "02.m2": "",
    }
    rows = {r.id: r for r in engine.evaluate_all(queries, model, 2)}
    assert (rows["01.m2"].status, rows["01.m2"].text) == ("ok", "2000")
    assert rows["06.m2"].text == "200.5"
    assert rows["33"].text == "0.1"
    assert rows["39"].text == "Habitação"
    assert rows["11"].text == "1" and rows["11"].message
    assert rows["13"].status == "error" and "SUM" in rows["13"].message
    assert rows["12"].status == "error"
    assert rows["05.m2"].text == "80.5"
    assert rows["02.m2"].status == "empty"


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
