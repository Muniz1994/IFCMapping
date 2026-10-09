"""What a form adapter has to provide."""
from __future__ import annotations

from typing import Protocol

from ..mapping import Parameter


class FormAdapter(Protocol):
    key: str               # stored in mapping files, e.g. "ine_xml"
    name: str              # shown in the UI
    template_suffix: str   # file type of the template, e.g. ".xml"
    output_suffix: str

    def parameters(self, template: bytes) -> list[Parameter]:
        """The parameters the template asks for, in document order (queries empty)."""
        ...

    def fill(self, template: bytes, values: dict[str, str]) -> bytes:
        """The template with each parameter's value written in. Missing ids are written empty."""
        ...

    def output_name(self, template_name: str) -> str:
        ...
