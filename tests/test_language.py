"""Checks (as-you-type diagnostics), completion and the model summary."""
import pytest

from ifcmapping.extractors.ifcq import IfcQueryExtractor

X = IfcQueryExtractor("IFC4")


def labels(text, source=None, pos=None):
    result = X.complete(text, len(text) if pos is None else pos, source)
    return [] if result is None else [o.label for o in result.options]


# --------------------------------------------------------------------------- diagnostics

def test_check_syntax_error_has_a_span():
    [d] = X.check('COUNT(IfcSpace[name = "x"])')
    assert d.severity == "error"
    assert 'COUNT(IfcSpace[name = "x"])'[d.start:d.end] == "name"
    assert "Did you mean Name?" in d.message


def test_check_unexpected_end_marks_last_character():
    text = "SUM(IfcSpace["
    [d] = X.check(text)
    assert (d.start, d.end) == (len(text) - 1, len(text))


def test_check_result_shape():
    assert X.check("") == []
    assert X.check("SUM(IfcSpace -> Qto_SpaceBaseQuantities.GrossFloorArea)") == []
    [d] = X.check("IfcSpace -> Qto_SpaceBaseQuantities.GrossFloorArea")
    assert d.severity == "warning" and "SUM" in d.message
    [d] = X.check("IfcSpace")
    assert d.severity == "info"


def test_check_quoted_enumeration_value():
    text = 'SUM(IfcSpace[PredefinedType = "GFA"] -> Qto_SpaceBaseQuantities.GrossFloorArea)'
    [d] = X.check(text)
    assert d.severity == "warning" and "without quotes" in d.message
    assert text[d.start:d.end] == '"GFA"'
    assert X.check('COUNT(IfcSpace[PredefinedType in ("FRACAO", "x")])') == []
    assert X.check("COUNT(IfcSpace[PredefinedType = GFA])") == []


def test_check_against_the_model(source):
    text = "SUM(IfcSpace -> Qto_SpaceBaseQuantities.GrossFloorAre)"
    [d] = X.check(text, source)
    assert d.severity == "warning" and "Did you mean GrossFloorArea?" in d.message
    assert text[d.start:d.end] == "Qto_SpaceBaseQuantities.GrossFloorAre"
    [d] = X.check("COUNT(IfcWall)", source)
    assert "no IfcWall" in d.message
    [d] = X.check("FIRST(IfcSite -> Pset_Nope.X)", source)
    assert "not in the model" in d.message
    assert X.check("COUNT(IfcProduct)", source) == []  # subtypes count


# --------------------------------------------------------------------------- completion

def test_complete_classes_at_statement_start(source):
    options = labels("Ifc", source)
    assert "IfcSpace" in options and "IfcWall" in options
    assert "SUM(" in options and "let " in options
    result = X.complete("Ifc", 3, source)
    assert result.start == 0
    space = next(o for o in result.options if o.label == "IfcSpace")
    assert space.detail == "2 in model"


def test_complete_new_line_is_a_new_statement():
    assert "let " in labels("let a = 1\n")
    assert "a" in labels("let a = 1\nlet b = 2\nx")  # variables


def test_complete_paths_in_filter_and_projection(source):
    for text in ("IfcSpace[", "SUM(IfcSpace -> ", 'IfcSpace[Name = "x" and '):
        options = labels(text, source)
        assert "Name" in options and "PredefinedType" in options
        assert "Qto_SpaceBaseQuantities." in options
        assert "Pset_SpaceCommon." in options  # standard template
        assert "ObjectPlacement" not in options  # entity-valued attribute


def test_complete_properties_after_dot(source):
    assert labels("IfcSite -> PTMU_Licenciamento.", source) == ["SuperficieTotal", "Uso"]
    assert "GrossFloorArea" in labels("IfcSpace[Qto_SpaceBaseQuantities.Gro", source)
    assert "IsExternal" in labels("IfcSpace[Pset_SpaceCommon.")  # from the template, no model


def test_complete_literals(source):
    options = labels("IfcSpace[PredefinedType = ", source)
    assert {"GFA", "PARKING", '"FRACAO"'} <= set(options)
    assert labels('IfcSite[PTMU_Licenciamento.Uso = ', source)[0] == '"Habitação"'
    assert labels("IfcBuildingStorey[Name = ", source)[0] == '"Piso 0"'
    assert labels('IfcSpace[Name in ("a", ', source)[:2] == ['"Sala 1"', '"Sala 2"']


def test_complete_replaces_open_quote(source):
    text = 'IfcSpace[PredefinedType = "FR'
    result = X.complete(text, len(text), source)
    assert text[result.start:] == '"FR'


@pytest.mark.parametrize("text", ["IfcSpace // Ifc", 'IfcSpace[Name = "Sala 1', "COUNT(IfcSpace))) Ifc"])
def test_no_completion(text):
    assert X.complete(text, len(text)) is None


def test_complete_mid_text(source):
    text = "SUM(IfcSpace -> Qto_SpaceBaseQuantities.)"
    assert "GrossFloorArea" in labels(text, source, pos=len(text) - 1)


# --------------------------------------------------------------------------- summary for the assistant

def test_describe(source):
    text = X.describe(source)
    assert "IfcSpace 2" in text
    assert 'IfcSpace: GFA 1, "FRACAO" 1' in text
    assert "Qto_SpaceBaseQuantities [IfcSpace 2]: GrossFloorArea: area 80.5..120" in text
    assert '"Habitação"' in text


def test_describe_truncates(source):
    text = X.describe(source, max_chars=200)
    assert "use search_model" in text


def test_search(source):
    assert "SuperficieTotal" in X.search(source, "superficie")
    assert X.search(source, "zzz").startswith("No match")


def test_data_types(source):
    assert source.index.data_types()["Qto_SpaceBaseQuantities.GrossFloorArea"] == "IFCAREAMEASURE"
