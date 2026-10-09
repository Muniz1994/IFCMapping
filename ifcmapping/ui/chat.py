"""The assistant panel on the right."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from nicegui import ui

from ..assistant import Assistant, AssistantError, Proposal
from ..mapping import Parameter

if TYPE_CHECKING:
    from .app import MappingPage

CSS = """
.ifcm-chat .q-message, .ifcm-chat .q-message-text, .ifcm-chat .q-message-container > div { max-width: 100%; min-width: 0; }
.ifcm-chat pre, .ifcm-chat code { white-space: pre-wrap; word-break: break-word; }
.ifcm-chat .q-scrollarea__content { width: 100%; }
"""

TOOL_LABELS = {
    "list_parameters": "Reading the parameter list",
    "get_parameters": "Reading parameters",
    "search_model": "Searching the model",
    "check_query": "Testing a query",
    "propose_query": "Proposing a query",
}


def _short_args(args: dict) -> str:
    parts = []
    for key, value in args.items():
        if key == "query":
            continue
        text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
        parts.append(text if len(text) <= 40 else text[:39] + "…")
    return ", ".join(parts)


class ChatPanel:
    def __init__(self, page: MappingPage):
        self.page = page
        self.assistant = Assistant(page.workspace)
        self.busy = False
        ui.add_css(CSS)
        with ui.column().classes("w-full h-full no-wrap gap-2 ifcm-chat"):
            with ui.row().classes("w-full items-center no-wrap"):
                ui.icon("auto_awesome").classes("text-primary")
                ui.label("Assistant").classes("text-subtitle1 text-weight-medium grow")
                ui.button(icon="restart_alt", on_click=self.new_chat).props("flat round dense") \
                    .tooltip("New conversation")
            self.scroll = ui.scroll_area().classes("w-full grow border rounded-borders")
            with self.scroll:
                self.messages = ui.column().classes("w-full gap-1")
            with self.messages:
                self._intro()
            with ui.row().classes("w-full items-end no-wrap gap-1"):
                self.input = ui.textarea(placeholder="Ask about the mapping… (Enter to send, Shift+Enter for a new line)") \
                    .props("outlined dense autogrow").classes("grow")
                self.input.on("keydown.enter", self._on_enter, js_handler="(e) => { if (!e.shiftKey) { e.preventDefault(); emit(e); } }")
                self.send_button = ui.button(icon="send", on_click=self.send).props("round unelevated dense")
            self.usage = ui.label(f"{self.assistant.model} · {self.assistant.usage}").classes("text-caption text-grey-7")

    def _intro(self) -> None:
        ui.markdown(
            "I can read and propose queries. Try:\n\n"
            "- *Which parameters can the model fill?*\n"
            "- *Write the query for 06.m2*\n"
            "- *Why does 03.m2 return no value?*"
        ).classes("text-caption text-grey-8 q-pa-sm")

    def new_chat(self) -> None:
        if self.busy:
            return
        self.assistant.reset()
        self.messages.clear()
        with self.messages:
            self._intro()
        self.usage.set_text(f"{self.assistant.model} · {self.assistant.usage}")

    def ask_about(self, param: Parameter) -> None:
        self.page.open_chat()
        self.input.set_value(f"Help me write the query for {param.id} ({param.label}).")
        self.input.run_method("focus")

    async def _on_enter(self) -> None:
        await self.send()

    async def send(self) -> None:
        text = (self.input.value or "").strip()
        if not text or self.busy:
            return
        self.busy = True
        self.input.set_value("")
        self.send_button.props("loading")
        with self.messages:
            ui.chat_message(text, sent=True).classes("w-full").props("bg-color=blue-1")
            with ui.chat_message(name="Assistant").classes("w-full").props("bg-color=grey-2") as reply:
                self.reply_column = ui.column().classes("w-full gap-1")
            with self.reply_column:
                spinner = ui.spinner("dots", size="sm")
        self.current_text = None
        self.current_buffer = ""
        try:
            await self.assistant.send(text, on_text=self._on_text, on_tool=self._on_tool)
        except AssistantError as err:
            with self.reply_column:
                ui.label(str(err)).classes("text-negative")
        except Exception as err:  # keep the panel usable
            with self.reply_column:
                ui.label(f"Unexpected error: {err}").classes("text-negative")
        finally:
            spinner.delete()
            if not self.reply_column.default_slot.children:
                reply.delete()
            self.busy = False
            self.send_button.props(remove="loading")
            self.usage.set_text(f"{self.assistant.model} · {self.assistant.usage}")
            self.scroll.scroll_to(percent=1.0)

    def _on_text(self, delta: str) -> None:
        if self.current_text is None:
            with self.reply_column:
                self.current_text = ui.markdown("")
            self.current_buffer = ""
        self.current_buffer += delta
        self.current_text.set_content(self.current_buffer)
        self.scroll.scroll_to(percent=1.0)

    def _on_tool(self, name: str, args: dict, result: str, is_error: bool) -> None:
        self.current_text = None  # text after a tool call starts a new block
        if name == "propose_query" and not is_error:
            return  # the proposal card is the record
        with self.reply_column:
            with ui.row().classes("items-center gap-1 text-caption text-grey-7"):
                ui.icon("error_outline" if is_error else "build", size="xs")
                ui.label(f"{TOOL_LABELS.get(name, name)}: {_short_args(args)}".rstrip(": "))
                if is_error:
                    ui.tooltip(result)

    def show_proposal(self, proposal: Proposal) -> ui.element:
        with self.reply_column:
            with ui.card().classes("w-full q-pa-sm bg-blue-1").props("flat") as box:
                with ui.row().classes("items-center gap-2"):
                    ui.badge(proposal.param_id).props("outline color=primary")
                    if proposal.preview:
                        ui.label(f"→ {proposal.preview}").classes("text-caption text-mono")
                ui.code(proposal.query).classes("w-full text-caption")
                with ui.row().classes("gap-2") as buttons:
                    ui.button("Accept", icon="check", on_click=lambda: self.page.resolve_proposal(proposal, True)) \
                        .props("dense unelevated size=sm")
                    ui.button("Reject", icon="close", on_click=lambda: self.page.resolve_proposal(proposal, False)) \
                        .props("dense flat size=sm")
                    ui.button("Show", icon="visibility", on_click=lambda: self.page.reveal(proposal.param_id)) \
                        .props("dense flat size=sm")
        box.buttons = buttons
        return box
