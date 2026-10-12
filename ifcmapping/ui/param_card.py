"""One parameter: header, query editor, live value and pending assistant proposals."""
from __future__ import annotations

from typing import TYPE_CHECKING

from nicegui import background_tasks, run, ui

from ..assistant import Proposal
from ..extractors import Diagnostic
from ..mapping import Parameter
from .query_editor import QueryEditor

if TYPE_CHECKING:
    from .app import MappingPage

STATUS_ICONS = {
    "empty": ("radio_button_unchecked", "ifcm-muted", "No query yet"),
    "ok": ("check_circle", "text-positive", "Valid"),
    "info": ("check_circle", "text-positive", "Valid"),
    "warning": ("warning", "text-warning", "Has warnings"),
    "error": ("error", "text-negative", "Has errors"),
}


class ParamCard:
    def __init__(self, page: MappingPage, param: Parameter):
        self.page = page
        self.param = param
        self.status = "empty"
        self._evaluation = 0
        with ui.card().classes("ifcm-card w-full q-px-md q-py-sm gap-1").props("flat") as self.card:
            with ui.row().classes("w-full items-center no-wrap gap-2"):
                with ui.icon("radio_button_unchecked", size="xs") as self.icon:
                    self.icon_tip = ui.tooltip("")
                ui.badge(param.id).props("outline color=primary").classes("text-mono")
                self.title = ui.label(param.title).classes("text-body2 grow").style("min-width: 0")
                with ui.label().classes("text-mono text-weight-medium") as self.value:
                    self.value_tip = ui.tooltip("")
                with ui.button(icon="more_vert").props("flat round dense size=sm"):
                    with ui.menu():
                        ui.menu_item("Run now (Ctrl+Enter)", self.evaluate_now)
                        ui.menu_item("Ask the assistant", lambda: page.chat.ask_about(param))
                        ui.menu_item("Edit details…", lambda: page.edit_parameter(param))
                        ui.menu_item("Delete parameter…", lambda: page.delete_parameter(param))
            self.notes = ui.label(param.notes).classes("text-caption ifcm-dim")
            self.notes.set_visibility(bool(param.notes))
            self.editor = QueryEditor(
                param.query,
                placeholder="e.g. SUM(IfcSpace -> Qto_SpaceBaseQuantities.GrossFloorArea)   ·   Ctrl+Space for suggestions",
                check=lambda text: page.extractor.check(text, page.source),
                complete=lambda text, pos: page.extractor.complete(text, pos, page.source),
                on_change=self._changed,
                on_diagnostics=self._diagnosed,
                on_run=self.evaluate_now,
            ).classes("w-full")
            self.proposals = ui.column().classes("w-full gap-1")
        self._set_status("empty" if not param.query.strip() else "ok")

    # ---- state ------------------------------------------------------------------------

    def refresh_header(self) -> None:
        self.title.set_text(self.param.title)
        self.notes.set_text(self.param.notes)
        self.notes.set_visibility(bool(self.param.notes))

    def matches(self, needle: str, status_filter: str) -> bool:
        if status_filter == "empty" and self.status != "empty":
            return False
        if status_filter == "problems" and self.status not in ("warning", "error"):
            return False
        hay = f"{self.param.id} {self.param.label} {self.param.query}".lower()
        return all(word in hay for word in needle.lower().split())

    def _set_status(self, status: str) -> None:
        self.status = status
        name, color, tip = STATUS_ICONS[status]
        self.icon.props(f"name={name}")
        self.icon.classes(replace=color)
        self.icon_tip.set_text(tip)

    def _changed(self, text: str) -> None:
        if text == self.param.query:
            return
        self.param.query = text
        self.page.mark_dirty()
        if not text.strip():
            self._set_status("empty")
        self.schedule_evaluation()

    def _diagnosed(self, diagnostics: list[Diagnostic]) -> None:
        if not self.param.query.strip():
            self._set_status("empty")
            return
        severities = {d.severity for d in diagnostics}
        self._set_status("error" if "error" in severities else "warning" if "warning" in severities else "ok")
        self.page.update_progress()

    # ---- evaluation ------------------------------------------------------------------------

    def schedule_evaluation(self) -> None:
        if self.page.source is not None:
            background_tasks.create(self._evaluate(), name=f"evaluate {self.param.id}")
        else:
            self.value.set_text("")

    def evaluate_now(self) -> None:
        if self.page.source is None:
            ui.notify("Load an IFC model to run queries.", type="info")
            return
        self.schedule_evaluation()

    async def _evaluate(self) -> None:
        self._evaluation += 1
        mine = self._evaluation
        source, query = self.page.source, self.param.query
        row = await run.io_bound(self.page.extractor.evaluate, self.param.id, query, source, self.page.decimals)
        if mine != self._evaluation:
            return  # a newer edit is being evaluated
        if row.status == "ok":
            self.value.set_text(f"= {row.text}" + (f" {self.param.unit}" if self.param.unit else ""))
            self.value.classes(replace="text-mono text-weight-medium text-primary")
        elif row.status == "error":
            self.value.set_text("error")
            self.value.classes(replace="text-mono text-weight-medium text-negative")
        else:
            self.value.set_text("no value" if query.strip() else "")
            self.value.classes(replace="text-mono text-weight-medium ifcm-muted")
        self.value_tip.set_text(row.message or query.strip()[:200])

    # ---- assistant proposals --------------------------------------------------------------

    def show_proposal(self, proposal: Proposal) -> ui.element:
        with self.proposals:
            with ui.card().classes("ifcm-proposal w-full q-pa-sm").props("flat") as box:
                with ui.row().classes("items-center gap-2"):
                    ui.icon("auto_awesome", size="xs").classes("text-primary")
                    ui.label("Assistant proposes").classes("text-caption text-weight-medium")
                    if proposal.preview:
                        ui.label(f"→ {proposal.preview}").classes("text-caption text-mono")
                if proposal.explanation:
                    ui.label(proposal.explanation).classes("text-caption")
                ui.code(proposal.query).classes("w-full text-caption")
                with ui.row().classes("gap-2"):
                    ui.button("Accept", icon="check", on_click=lambda: self.page.resolve_proposal(proposal, True)) \
                        .props("dense unelevated size=sm")
                    ui.button("Reject", icon="close", on_click=lambda: self.page.resolve_proposal(proposal, False)) \
                        .props("dense flat size=sm")
        return box
