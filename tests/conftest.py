from pathlib import Path

import ifcopenshell
import ifcopenshell.api
import pytest

from ifcmapping.extractors.ifcq import IfcSource

TEMPLATE = (Path(__file__).parent.parent / "EdificacaoEDemolicao.xml").read_bytes()


def build_model() -> ifcopenshell.file:
    f = ifcopenshell.file(schema="IFC4")
    run = ifcopenshell.api.run
    project = run("root.create_entity", f, ifc_class="IfcProject", name="P")
    run("unit.assign_unit", f)
    site = run("root.create_entity", f, ifc_class="IfcSite", name="Site")
    building = run("root.create_entity", f, ifc_class="IfcBuilding", name="B")
    storey = run("root.create_entity", f, ifc_class="IfcBuildingStorey", name="Piso 0")
    run("aggregate.assign_object", f, products=[site], relating_object=project)
    run("aggregate.assign_object", f, products=[building], relating_object=site)
    run("aggregate.assign_object", f, products=[storey], relating_object=building)

    pset = run("pset.add_pset", f, product=site, name="PTMU_Licenciamento")
    run("pset.edit_pset", f, pset=pset, properties={"SuperficieTotal": 2000.0, "Uso": "Habitação"})

    for name, area, predefined in [("Sala 1", 120.0, "GFA"), ("Sala 2", 80.5, "FRACAO")]:
        space = run("root.create_entity", f, ifc_class="IfcSpace", name=name)
        if predefined == "GFA":
            space.PredefinedType = "GFA"
        else:
            space.PredefinedType, space.ObjectType = "USERDEFINED", predefined
        run("aggregate.assign_object", f, products=[space], relating_object=storey)
        qto = run("pset.add_qto", f, product=space, name="Qto_SpaceBaseQuantities")
        run("pset.edit_qto", f, qto=qto, properties={"GrossFloorArea": area})
    return f


@pytest.fixture(scope="session")
def model():
    return build_model()


@pytest.fixture(scope="session")
def source(model):
    return IfcSource(model, "test.ifc")
