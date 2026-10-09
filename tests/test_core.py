import xml.etree.ElementTree as ET
from pathlib import Path

import ifcopenshell
import ifcopenshell.api
import pytest

import ine_form
import query_engine

TEMPLATE = (Path(__file__).parent.parent / "EdificacaoEDemolicao.xml").read_bytes()
NS = {"f": ine_form.NS}


# --------------------------------------------------------------------------- ine_form

def test_load_parameters():
    params = ine_form.load_parameters(TEMPLATE)
    assert len(params) == 45
    assert params[0] == ine_form.Parameter("01.m2", "SUPERFÍCIE TOTAL DO TERRENO OBJETO DA OPERAÇÃO URBANÍSTICA", "m2")
    by_nome = {p.nome: p for p in params}
    assert by_nome["07.m3"].unit == "m3"
    assert by_nome["08.m"].unit == "m"
    assert by_nome["11"].unit is None
    assert len(by_nome) == len(params)  # nome is unique


def test_fill_xml():
    out = ine_form.fill_xml(TEMPLATE, {"01.m2": "2000", "39": "Habitação"})
    root = ET.fromstring(out)
    values = {v.get("nome"): v.text for v in root.iterfind(".//f:dados/f:v", NS)}
    assert values["01.m2"] == "2000"
    assert values["39"] == "Habitação"
    assert values["02.m2"] is None  # empty
    assert root.find("f:header", NS).get("chave") == "046B7652-F415-4EE3-BB0E-33F717F4977C"
    assert root.find(".//f:info/f:i", NS).text == "ANEXO-IC"
    text = out.decode("utf-8")
    assert 'xmlns="http://ine.pt/public/xsd/forms"' in text
    assert 'xsi:schemaLocation="http://ine.pt/public/xsd/forms upload_v1.xsd"' in text
    assert '<v nome="02.m2"></v>' in text
    assert "ns0:" not in text


# --------------------------------------------------------------------------- formatting

@pytest.mark.parametrize("value, expected", [
    (None, ""), (3, "3"), (3.0, "3"), (2.345, "2.35"), (2.5, "2.5"),
    (0.1 + 0.2, "0.3"), ("Habitação", "Habitação"), (float("nan"), ""), (True, "true"),
])
def test_format_value(value, expected):
    assert query_engine.format_value(value, 2) == expected


def test_parse_data_types():
    text = "Qto.A = ifcareameasure\n\n// comment\nP.B=IFCLABEL  // trailing"
    assert query_engine.parse_data_types(text) == {"Qto.A": "IFCAREAMEASURE", "P.B": "IFCLABEL"}
    with pytest.raises(ValueError):
        query_engine.parse_data_types("nonsense")


# --------------------------------------------------------------------------- against a model

@pytest.fixture(scope="module")
def model():
    f = ifcopenshell.file(schema="IFC4")
    project = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcProject", name="P")
    ifcopenshell.api.run("unit.assign_unit", f)
    site = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcSite", name="Site")
    building = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcBuilding", name="B")
    storey = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcBuildingStorey", name="Piso 0")
    ifcopenshell.api.run("aggregate.assign_object", f, products=[site], relating_object=project)
    ifcopenshell.api.run("aggregate.assign_object", f, products=[building], relating_object=site)
    ifcopenshell.api.run("aggregate.assign_object", f, products=[storey], relating_object=building)

    pset = ifcopenshell.api.run("pset.add_pset", f, product=site, name="PTMU_Licenciamento")
    ifcopenshell.api.run("pset.edit_pset", f, pset=pset, properties={"SuperficieTotal": 2000.0, "Uso": "Habitação"})

    for name, area in [("Sala 1", 120.0), ("Sala 2", 80.5)]:
        space = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcSpace", name=name)
        ifcopenshell.api.run("aggregate.assign_object", f, products=[space], relating_object=storey)
        qto = ifcopenshell.api.run("pset.add_qto", f, product=space, name="Qto_SpaceBaseQuantities")
        ifcopenshell.api.run("pset.edit_qto", f, qto=qto, properties={"GrossFloorArea": area})
    return f


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
        "02.m2": "",
    }
    rows = {r.nome: r for r in query_engine.evaluate_all(queries, model, 2)}
    assert (rows["01.m2"].status, rows["01.m2"].text) == ("ok", "2000")
    assert rows["06.m2"].text == "200.5"
    assert rows["33"].text == "0.1"
    assert rows["39"].text == "Habitação"
    assert rows["11"].text == "1" and rows["11"].message
    assert rows["13"].status == "error" and "SUM" in rows["13"].message
    assert rows["12"].status == "error"
    assert rows["02.m2"].status == "empty"


def test_validate():
    assert query_engine.validate("COUNT(IfcSpace)", "IFC4") is None
    assert query_engine.validate("COUNT(IfcSpace[name = \"x\"])", "IFC4")


def test_build_ids():
    queries = {
        "a": "SUM(IfcSpace -> Qto_SpaceBaseQuantities.GrossFloorArea)",
        "b": "let x = FIRST(IfcSite -> PTMU_Licenciamento.SuperficieTotal)\nx",
        "c": "let x = COUNT(IfcSpace)\nx",  # same let name in another parameter
        "d": "",
    }
    result = query_engine.build_ids(queries, "IFC4", "Test", {"PTMU_Licenciamento.SuperficieTotal": "IFCAREAMEASURE"})
    xml = result.to_string()
    assert "GrossFloorArea" in xml and "SuperficieTotal" in xml
    with pytest.raises(ValueError):
        query_engine.build_ids({"a": " "}, "IFC4", "Empty")
    with pytest.raises(ValueError, match="IDS would be empty"):
        query_engine.build_ids({"a": "COUNT(IfcSpace)"}, "IFC4", "Nothing required")
