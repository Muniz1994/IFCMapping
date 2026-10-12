"""The IFCMapping page: parameters and queries, results, IDS, and the assistant."""
from __future__ import annotations

import json
from pathlib import Path

import ifcquery
from nicegui import background_tasks, events, run, ui

from ..assistant import Proposal, Workspace
from ..extractors import Row
from ..extractors.ifcq import SCHEMAS, IfcQueryExtractor
from ..extractors.ifcq import engine as ifcq_engine
from ..forms import get_form
from ..mapping import MappingSet, Parameter
from .chat import ChatPanel
from . import theme
from .param_card import ParamCard

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TEMPLATE = ROOT / "EdificacaoEDemolicao.xml"
MAPPING_FILE = ROOT / "mapping.json"
LEGACY_QUERIES = ROOT / "queries.json"


def initial_mapping(template: bytes) -> tuple[MappingSet, str]:
    """mapping.json if present; else the template's parameters with queries from a legacy queries.json."""
    if MAPPING_FILE.exists():
        return MappingSet.load(MAPPING_FILE), f"Loaded {MAPPING_FILE.name}"
    form = get_form("ine_xml")
    mapping = MappingSet(form=form.key, parameters=form.parameters(template))
    if LEGACY_QUERIES.exists():
        mapping.apply_queries(json.loads(LEGACY_QUERIES.read_text(encoding="utf-8")))
        return mapping, f"Imported queries from {LEGACY_QUERIES.name}; Save writes {MAPPING_FILE.name}"
    return mapping, f"New mapping from {DEFAULT_TEMPLATE.name}"


class MappingPage:
    def __init__(self) -> None:
        self.template = DEFAULT_TEMPLATE.read_bytes()
        self.template_name = DEFAULT_TEMPLATE.name
        self.mapping, startup_message = initial_mapping(self.template)
        self.form = get_form(self.mapping.form)
        self.extractor = IfcQueryExtractor("IFC4")
        self.source = None
        self.decimals = 2
        self.dirty = False
        self.cards: dict[str, ParamCard] = {}
        self.proposal_boxes: dict[int, list[ui.element]] = {}
        self.workspace = Workspace(self.mapping, self.extractor, on_proposal=self.show_proposal)
        background_tasks.create(run.io_bound(self.extractor.warm_up), name="load pset templates")

        self._header()
        with ui.right_drawer(value=True, bordered=True).props("width=460").classes("q-pa-sm") as self.drawer:
            self.chat = ChatPanel(self)
        with ui.column().classes("w-full max-w-5xl mx-auto q-pa-md gap-3"):
            with ui.tabs().classes("w-full").props("align=left dense") as tabs:
                tab_map = ui.tab("Mappings", icon="edit_note")
                tab_results = ui.tab("Results & form", icon="table_view")
                tab_ids = ui.tab("IDS", icon="rule")
            with ui.tab_panels(tabs, value=tab_map).classes("w-full").props("keep-alive"):
                with ui.tab_panel(tab_map).classes("q-pa-none"):
                    self._mappings_tab()
                with ui.tab_panel(tab_results).classes("q-pa-none"):
                    self._results_tab()
                with ui.tab_panel(tab_ids).classes("q-pa-none"):
                    self._ids_tab()
        ui.notify(startup_message)

    # ---- header -------------------------------------------------------------------------------

    def _header(self) -> None:
        with ui.header(elevated=False).classes("ifcm-header items-center gap-3 q-px-lg q-py-sm"):
            with ui.row().classes("items-center gap-2 no-wrap"):
                ui.icon("view_in_ar", size="sm").style(f"color: {theme.BLUE_LIGHT}")
                ui.label("IFCMapping").classes("ifcm-brand text-h6")
            self.template_label = ui.label().classes("text-caption ifcm-dim")
            self._update_template_label()
            ui.space()
            self.model_chip = ui.chip("No model", icon="view_in_ar", on_click=self.load_model_dialog) \
                .props("outline clickable color=grey-6").tooltip("Load an IFC model")
            self.schema_select = ui.select(list(SCHEMAS), value=self.extractor.schema,
                                           on_change=lambda e: self.set_schema(e.value)) \
                .props("dense outlined options-dense").classes("w-40").tooltip("IFC schema for checking and IDS")
            self.save_button = ui.button("Save", icon="save", on_click=self.save).props("unelevated dense")
            with ui.button(icon="more_vert").props("flat round dense"):
                with ui.menu():
                    ui.menu_item("Download mapping", self.download_mapping)
                    ui.menu_item("Open mapping or queries file…", self.upload_mapping_dialog)
                    ui.separator()
                    ui.menu_item("Load form template…", self.upload_template_dialog)
                    ui.menu_item("Query language reference", self.show_reference)
            ui.button(icon="auto_awesome", on_click=lambda: self.drawer.toggle()).props("flat round dense") \
                .tooltip("Assistant")

    def _update_template_label(self) -> None:
        self.template_label.set_text(f"{self.form.name}: {self.template_name} · {len(self.mapping.parameters)} parameters")

    def open_chat(self) -> None:
        self.drawer.show()

    # ---- mappings tab ---------------------------------------------------------------------------

    def _mappings_tab(self) -> None:
        with ui.row().classes("w-full items-center gap-2 q-mb-sm"):
            self.search = ui.input(placeholder="Filter parameters…", on_change=self.apply_filter) \
                .props("dense outlined clearable").classes("w-64")
            with self.search.add_slot("prepend"):
                ui.icon("search")
            self.status_filter = ui.toggle({"all": "All", "empty": "Empty", "problems": "Problems"}, value="all",
                                           on_change=self.apply_filter).props("dense no-caps unelevated")
            ui.space()
            self.progress = ui.label().classes("text-caption ifcm-dim")
            ui.button("Add parameter", icon="add", on_click=self.add_parameter).props("flat dense no-caps")
        self.card_list = ui.column().classes("w-full gap-2")
        self.build_cards()

    def build_cards(self) -> None:
        self.card_list.clear()
        self.cards.clear()
        with self.card_list:
            for param in self.mapping.parameters:
                self.cards[param.id] = ParamCard(self, param)
        self.update_progress()
        self._update_template_label()

    def apply_filter(self) -> None:
        needle = self.search.value or ""
        for card in self.cards.values():
            card.card.set_visibility(card.matches(needle, self.status_filter.value))

    def update_progress(self) -> None:
        cards = list(self.cards.values())
        filled = sum(1 for c in cards if c.status != "empty")
        problems = sum(1 for c in cards if c.status in ("warning", "error"))
        text = f"{filled} of {len(cards)} have a query"
        self.progress.set_text(text + (f" · {problems} with problems" if problems else ""))

    def mark_dirty(self) -> None:
        if not self.dirty:
            self.dirty = True
            self.save_button.props("color=warning")
        self.update_progress()

    def reveal(self, param_id: str) -> None:
        card = self.cards.get(param_id)
        if card is not None:
            card.card.set_visibility(True)
            ui.run_javascript(f'getHtmlElement({card.card.id}).scrollIntoView({{behavior: "smooth", block: "center"}})')

    # ---- parameters: add / edit / delete --------------------------------------------------------

    def _parameter_dialog(self, title: str, param: Parameter | None, on_save) -> None:
        with ui.dialog() as dialog, ui.card().classes("w-96"):
            ui.label(title).classes("text-h6")
            pid = ui.input("Id", value=param.id if param else "").props("dense outlined").classes("w-full")
            if param is not None:
                pid.props("readonly")
            label = ui.input("Label", value=param.label if param else "").props("dense outlined").classes("w-full")
            unit = ui.input("Unit", value=(param.unit or "") if param else "").props("dense outlined").classes("w-full")
            notes = ui.textarea("Notes (also read by the assistant)", value=param.notes if param else "") \
                .props("dense outlined autogrow").classes("w-full")

            def submit() -> None:
                try:
                    on_save(pid.value.strip(), label.value.strip(), unit.value.strip() or None, notes.value.strip())
                except ValueError as err:
                    ui.notify(str(err), type="negative")
                    return
                dialog.close()

            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=dialog.close).props("flat")
                ui.button("Save", on_click=submit).props("unelevated")
        dialog.open()

    def add_parameter(self) -> None:
        def save(pid, label, unit, notes):
            param = Parameter(pid, label, unit, notes=notes)
            self.mapping.add(param)
            with self.card_list:
                self.cards[pid] = ParamCard(self, param)
            self.mark_dirty()
            self._update_template_label()
            self.reveal(pid)
        self._parameter_dialog("Add parameter", None, save)

    def edit_parameter(self, param: Parameter) -> None:
        def save(_pid, label, unit, notes):
            param.label, param.unit, param.notes = label, unit, notes
            self.cards[param.id].refresh_header()
            self.mark_dirty()
        self._parameter_dialog(f"Parameter {param.id}", param, save)

    async def delete_parameter(self, param: Parameter) -> None:
        with ui.dialog() as dialog, ui.card():
            ui.label(f"Delete parameter {param.id}?").classes("text-subtitle1")
            ui.label(param.title).classes("text-caption")
            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=lambda: dialog.submit(False)).props("flat")
                ui.button("Delete", on_click=lambda: dialog.submit(True)).props("unelevated color=negative")
        if await dialog:
            self.mapping.remove(param.id)
            self.cards.pop(param.id).card.delete()
            self.mark_dirty()
            self._update_template_label()

    # ---- proposals ----------------------------------------------------------------------------------

    def show_proposal(self, proposal: Proposal) -> None:
        boxes = [self.chat.show_proposal(proposal)]
        card = self.cards.get(proposal.param_id)
        if card is not None:
            boxes.append(card.show_proposal(proposal))
        self.proposal_boxes[id(proposal)] = boxes

    def resolve_proposal(self, proposal: Proposal, accepted: bool) -> None:
        boxes = self.proposal_boxes.pop(id(proposal), [])
        card = self.cards.get(proposal.param_id)
        if accepted and card is not None:
            card.editor.set_value(proposal.query)
        for box in boxes[1:]:
            box.delete()
        if boxes:  # keep the chat card as a record, without its buttons
            chat_box = boxes[0]
            chat_box.buttons.clear()
            with chat_box.buttons:
                ui.label("Accepted" if accepted else "Rejected") \
                    .classes("text-caption " + ("text-positive" if accepted else "ifcm-muted"))
        if proposal in self.workspace.proposals:
            self.workspace.proposals.remove(proposal)

    # ---- model, schema, files ----------------------------------------------------------------------

    def load_model_dialog(self) -> None:
        with ui.dialog() as dialog, ui.card().classes("w-96"):
            ui.label("Load an IFC model").classes("text-h6")
            ui.label("It stays on this computer. The assistant only gets a short summary of it.") \
                .classes("text-caption ifcm-dim")

            async def handle(e: events.UploadEventArguments) -> None:
                dialog.close()
                notification = ui.notification(f"Opening {e.file.name}…", spinner=True, timeout=None)
                try:
                    data = await e.file.read()
                    source = await run.io_bound(self.extractor.open, data, e.file.name)
                except Exception as err:
                    notification.dismiss()
                    ui.notify(f"Could not open the IFC file: {err}", type="negative")
                    return
                notification.dismiss()
                self.set_source(source)

            ui.upload(on_upload=handle, auto_upload=True).props("accept=.ifc flat bordered").classes("w-full")
        dialog.open()

    def set_source(self, source) -> None:
        self.source = source
        self.workspace.source = source
        self.model_chip.set_text(f"{source.name} · {source.schema}")
        self.model_chip.props("color=primary")
        if source.schema.upper() != self.extractor.schema.upper():
            if source.schema not in self.schema_select.options:
                self.schema_select.set_options([*self.schema_select.options, source.schema])
            self.schema_select.set_value(source.schema)  # calls set_schema
            ui.notify(f"Schema set to {source.schema} to match the model.")
        else:
            self.relint_all()
        for card in self.cards.values():
            card.schedule_evaluation()
        ui.notify(f"Loaded {source.name}: {sum(source.index.class_counts.values()):,} objects.", type="positive")

    def set_schema(self, schema: str) -> None:
        self.extractor.schema = schema
        background_tasks.create(run.io_bound(self.extractor.warm_up), name="load pset templates")
        self.relint_all()

    def relint_all(self) -> None:
        for card in self.cards.values():
            card.editor.relint()

    def save(self) -> None:
        self.mapping.save(MAPPING_FILE)
        self.dirty = False
        self.save_button.props("color=primary")
        ui.notify(f"Saved {MAPPING_FILE.name}", type="positive")

    def download_mapping(self) -> None:
        ui.download.content(self.mapping.to_json(), "mapping.json", "application/json")

    def upload_mapping_dialog(self) -> None:
        with ui.dialog() as dialog, ui.card().classes("w-96"):
            ui.label("Open a mapping").classes("text-h6")
            ui.label("A mapping.json replaces the current mapping. A flat queries.json "
                     "({id: query}) only sets the queries of matching parameters.").classes("text-caption")

            async def handle(e: events.UploadEventArguments) -> None:
                dialog.close()
                try:
                    data = json.loads(await e.file.text())
                    incoming = MappingSet.from_dict(data)
                except (ValueError, UnicodeDecodeError) as err:
                    ui.notify(f"Invalid file: {err}", type="negative")
                    return
                if "parameters" in data:
                    self.mapping.form, self.mapping.extractor = incoming.form, incoming.extractor
                    self.mapping.parameters[:] = incoming.parameters
                    message = f"Opened {e.file.name}: {len(incoming.parameters)} parameters."
                else:
                    unknown = self.mapping.apply_queries(incoming.queries())
                    message = f"Loaded queries from {e.file.name}." + \
                        (f" Ignored unknown ids: {', '.join(unknown)}" if unknown else "")
                self.build_cards()
                self.mark_dirty()
                ui.notify(message, type="positive")

            ui.upload(on_upload=handle, auto_upload=True).props("accept=.json flat bordered").classes("w-full")
        dialog.open()

    def upload_template_dialog(self) -> None:
        with ui.dialog() as dialog, ui.card().classes("w-96"):
            ui.label("Load a form template").classes("text-h6")
            ui.label("Parameters missing from the mapping are added; existing queries are kept.") \
                .classes("text-caption")

            async def handle(e: events.UploadEventArguments) -> None:
                dialog.close()
                data = await e.file.read()
                try:
                    params = self.form.parameters(data)
                except Exception as err:
                    ui.notify(f"Could not read the template: {err}", type="negative")
                    return
                self.template, self.template_name = data, e.file.name
                added = self.mapping.merge_parameters(params)
                self.build_cards()
                if added:
                    self.mark_dirty()
                ui.notify(f"Template loaded; {len(added)} new parameters.", type="positive")

            ui.upload(on_upload=handle, auto_upload=True) \
                .props(f"accept={self.form.template_suffix} flat bordered").classes("w-full")
        dialog.open()

    def show_reference(self) -> None:
        with ui.dialog() as dialog, ui.card().classes("w-full").style("max-width: 900px"):
            ui.markdown(self.extractor.language_help)
            ui.button("Close", on_click=dialog.close).props("flat")
        dialog.open()

    # ---- results tab ----------------------------------------------------------------------------------

    def _results_tab(self) -> None:
        with ui.row().classes("w-full items-center gap-3 q-mb-sm"):
            ui.button("Run all queries", icon="play_arrow", on_click=self.run_all).props("unelevated")
            ui.number("Decimal places", value=self.decimals, min=0, max=6, step=1,
                      on_change=lambda e: setattr(self, "decimals", int(e.value or 0))) \
                .props("dense outlined").classes("w-36")
            ui.space()
            self.results_summary = ui.label().classes("text-caption ifcm-dim")
        columns = [
            {"name": "status", "label": "", "field": "status", "align": "center"},
            {"name": "id", "label": "Code", "field": "id", "align": "left"},
            {"name": "parameter", "label": "Parameter", "field": "parameter", "align": "left"},
            {"name": "value", "label": "Value", "field": "value", "align": "right"},
            {"name": "unit", "label": "Unit", "field": "unit", "align": "left"},
            {"name": "message", "label": "Message", "field": "message", "align": "left"},
        ]
        self.results_table = ui.table(columns=columns, rows=[], row_key="id", pagination=0) \
            .props("dense flat bordered wrap-cells").classes("w-full")
        with ui.row().classes("w-full items-center gap-2 q-mt-sm") as self.export_row:
            ui.button("Download filled form", icon="download", on_click=self.download_form).props("unelevated")
            self.form_preview = ui.expansion("Preview").classes("w-full")
        self.export_row.set_visibility(False)
        self.rows: list[Row] = []

    async def run_all(self) -> None:
        if self.source is None:
            ui.notify("Load an IFC model first.", type="warning")
            self.load_model_dialog()
            return
        source, decimals = self.source, self.decimals
        params = list(self.mapping.parameters)
        self.rows = await run.io_bound(
            lambda: [self.extractor.evaluate(p.id, p.query, source, decimals) for p in params])
        icons = {"ok": "✅", "empty": "▫️", "error": "❌"}
        by_id = {p.id: p for p in params}
        self.results_table.rows = [{
            "status": icons[r.status], "id": r.id, "parameter": by_id[r.id].label,
            "value": r.text, "unit": by_id[r.id].unit or "", "message": r.message,
        } for r in self.rows]
        self.results_table.update()
        counts = {s: sum(1 for r in self.rows if r.status == s) for s in icons}
        self.results_summary.set_text(f"{counts['ok']} filled · {counts['empty']} empty · {counts['error']} errors")
        self.form_preview.clear()
        with self.form_preview:
            ui.code(self._filled_form().decode("utf-8"), language="xml").classes("w-full")
        self.export_row.set_visibility(True)

    def _filled_form(self) -> bytes:
        return self.form.fill(self.template, {r.id: r.text for r in self.rows})

    def download_form(self) -> None:
        ui.download.content(self._filled_form(), self.form.output_name(self.template_name), "application/xml")

    # ---- IDS tab ----------------------------------------------------------------------------------------

    def _ids_tab(self) -> None:
        ui.label("Every attribute and property the queries read becomes an IDS requirement.") \
            .classes("text-caption ifcm-dim")
        self.ids_title = ui.input("IDS title", value="INE - Edificação e Demolição").props("dense outlined") \
            .classes("w-full")
        self.ids_types = ui.textarea("Property data types (optional, one per line)",
                                     placeholder="Qto_SpaceBaseQuantities.GrossFloorArea=IFCAREAMEASURE") \
            .props("dense outlined autogrow").classes("w-full")
        with ui.row().classes("gap-2"):
            ui.button("Generate IDS", icon="rule", on_click=self.generate_ids).props("unelevated")
            ui.button("Fill data types from model", icon="auto_fix_high", on_click=self.fill_data_types) \
                .props("flat")
        self.ids_output = ui.column().classes("w-full")

    def fill_data_types(self) -> None:
        if self.source is None:
            ui.notify("Load an IFC model first.", type="warning")
            return
        used = "\n".join(p.query for p in self.mapping.parameters)
        types = {key: t for key, t in self.source.index.data_types().items() if key.split(".", 1)[1] in used}
        self.ids_types.set_value("\n".join(f"{k}={v}" for k, v in sorted(types.items())))
        ui.notify(f"{len(types)} data types from the model.")

    def generate_ids(self) -> None:
        self.ids_output.clear()
        try:
            data_types = ifcq_engine.parse_data_types(self.ids_types.value or "")
            result = self.extractor.build_ids(self.mapping.queries(), self.ids_title.value, data_types)
            xml = result.to_string()
        except ifcquery.IfcQueryError as err:
            ui.notify(f"Query error: {ifcq_engine.describe_error(err)}", type="negative")
            return
        except ValueError as err:
            ui.notify(str(err), type="negative")
            return
        with self.ids_output:
            for warning in result.warnings:
                ui.label(f"⚠ {warning}").classes("text-caption text-warning")
            ui.button("Download IDS", icon="download",
                      on_click=lambda: ui.download.content(xml, "EdificacaoEDemolicao.ids", "application/xml")) \
                .props("unelevated")
            with ui.expansion("Preview").classes("w-full"):
                ui.code(xml, language="xml").classes("w-full")


def main(reload: bool = False, port: int = 8080, native: bool = False) -> None:
    @ui.page("/")
    def index() -> None:
        ui.page_title("IFCMapping")
        theme.apply()
        MappingPage()

    ui.run(title="IFCMapping", reload=reload, port=port, native=native, favicon="🏗️", show=False)
