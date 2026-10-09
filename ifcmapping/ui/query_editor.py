"""A NiceGUI element wrapping the CodeMirror query editor (query_editor.js).

Linting and completion requests from the browser are answered by the given
``check`` and ``complete`` callables, so the element itself knows nothing about
the query language. The CodeMirror bundle is built from ``editor/`` (see its
package.json).
"""
from __future__ import annotations

from typing import Callable

from nicegui import ui
from nicegui.events import GenericEventArguments

from ..extractors import CompletionResult, Diagnostic

CheckFn = Callable[[str], list[Diagnostic]]
CompleteFn = Callable[[str, int], CompletionResult | None]


class QueryEditor(ui.element, component="query_editor.js", esm={"ifcq-codemirror": "editor/dist"}):
    def __init__(
        self,
        value: str = "",
        *,
        placeholder: str = "",
        check: CheckFn | None = None,
        complete: CompleteFn | None = None,
        on_change: Callable[[str], None] | None = None,
        on_diagnostics: Callable[[list[Diagnostic]], None] | None = None,
        on_run: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self._value = value
        self._props["value"] = value
        self._props["placeholder"] = placeholder
        self._check = check
        self._complete = complete
        self._on_change = on_change
        self._on_diagnostics = on_diagnostics
        self.on("change", self._handle_change)
        self.on("request", self._handle_request)
        if on_run is not None:
            self.on("run", lambda _: on_run())

    @property
    def value(self) -> str:
        return self._value

    def set_value(self, text: str) -> None:
        """Replace the text from Python (the browser keeps its own edits otherwise)."""
        self._value = text
        self._props["value"] = text
        self.update()
        if self._on_change is not None:
            self._on_change(text)

    def relint(self) -> None:
        self.run_method("relint")

    def _handle_change(self, e: GenericEventArguments) -> None:
        self._value = e.args if isinstance(e.args, str) else ""
        self._props["value"] = self._value  # so a re-render shows the latest text
        if self._on_change is not None:
            self._on_change(self._value)

    def _handle_request(self, e: GenericEventArguments) -> None:
        args = e.args
        result = None
        try:
            if args["kind"] == "lint" and self._check is not None:
                diagnostics = self._check(args["text"])
                result = [d.to_dict() for d in diagnostics]
                if self._on_diagnostics is not None:
                    self._on_diagnostics(diagnostics)
            elif args["kind"] == "complete" and self._complete is not None:
                completion = self._complete(args["text"], int(args["pos"]))
                result = completion.to_dict() if completion else None
        finally:
            self.run_method("resolve", args["id"], result)
