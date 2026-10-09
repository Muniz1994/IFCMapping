Each parameter has one IFCQuery query. The **last statement** gives the parameter's value: it must be a single value (a number or text). A bare element selection is counted.

```
IfcSpace                                   // all spaces (subtypes included)
IfcSpace[Name = "Sala 1"]                  // filter on a direct attribute
IfcSpace[Pset_X.Prop >= 10]                // filter on a property: PropertySet.Property
IfcSpace[PredefinedType = GFA]             // bare UPPERCASE = enumeration, checked against the schema
IfcSpace[PredefinedType = "FRACAO"]        // string = USERDEFINED with ObjectType/ElementType "FRACAO"
IfcSpace[P.A in ("x", "y") and not exists(P.B) or P.C ~= "logistica"]
IfcBuildingStorey[Name = "Piso 0"] > IfcSpace          // containment, any depth
IfcSpace -> Qto_SpaceBaseQuantities.NetFloorArea       // projection to values (SI units for quantities)
COUNT(x)  SUM(x)  AVG(x)  MIN(x)  MAX(x)  FIRST(x)
let a = SUM(IfcSpace -> Qto_SpaceBaseQuantities.GrossFloorArea)
let b = FIRST(IfcSite -> PTMU_Licenciamento.SuperficieTotal)
a / b                                      // last statement = the parameter value
"Identity Data"."Assembly Code"            // quote names with spaces
// comment   (# is NOT a comment)
```

Operators: `= != < <= > >= ~=` (`~=` ignores case and accents), `in (...)`, `exists(path)`. Precedence: `not`, then `and`, then `or`. Arithmetic: `+ - * /`.

Rules:
1. Strings are always double-quoted. A bare word in value position must be an UPPERCASE enumeration value valid for that attribute.
2. Identifiers starting with `Ifc` are class names, so they can't be `let` names.
3. A non-dotted path must be a real schema attribute of the class (case-sensitive: `Name`, not `name`). Properties always need `PsetName.PropName`.
4. `SUM/AVG/MIN/MAX` need a value list: `SUM(IfcSpace -> Qto.X)`, not `SUM(IfcSpace)`. `COUNT` takes elements or values.
5. In a filter, a missing value makes every comparison false, including `!=`. Use `exists()`.
6. `>` means containment only when an IFC class follows; otherwise it is greater-than.
7. One statement per line. A statement continues onto the next line inside `()`/`[]`, or when the line starts with a binary operator such as `->`, `and`, `+`.
8. `let` names can't be rebound. `count sum avg min max first let and or not in exists true false` are reserved.
9. Ordering comparisons (`<`, `>`, ...) need numbers.
10. Quantities are returned in SI units (m, m², m³).
