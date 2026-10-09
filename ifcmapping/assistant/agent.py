"""The chat assistant: Claude with the mapping tools.

Token use is kept low by:
- never sending the model itself, only a compact summary (``Extractor.describe``),
  with ``search_model`` for anything beyond it;
- reading mappings through tools instead of pasting them into every request;
- prompt caching: tools, instructions and the model summary form a fixed,
  cached prefix, and the conversation is cached up to its last turn;
- appending (never editing) history; a model loaded mid-conversation is
  announced in a mid-conversation system message so the cached prefix stays valid.
"""
from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass
from typing import Awaitable, Callable

import anthropic

from .tools import TOOLS, Workspace, run_tool

DEFAULT_MODEL = os.environ.get("IFCMAPPING_MODEL", "claude-opus-5-5")
DEFAULT_EFFORT = os.environ.get("IFCMAPPING_EFFORT", "medium")
MAX_TOOL_ROUNDS = 15
NO_CREDENTIALS = ("No Anthropic credentials. Set ANTHROPIC_API_KEY or run `ant auth login`, "
                  "then restart the app.")
# Models that accept the server-side refusal fallback (`fallbacks: "default"`).
_FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}

INSTRUCTIONS = """\
You help the user map data from a building model to the parameters of a form. Each parameter's value \
is computed by one query; the user edits queries in an editor next to this chat.

How to work:
- Read the mapping with list_parameters and get_parameters. Look up property sets and properties with \
search_model before writing a query that uses them. Never guess names that the model summary or \
search_model can tell you.
- Test queries with check_query, then suggest them with propose_query. The user accepts or rejects each \
proposal; never say a mapping was saved or changed.
- When the model lacks the data a parameter needs, say so and say what would have to be added to the model.
- Be brief. Do not repeat a proposed query in your reply; the app shows it.
- Reply in the user's language.

Query language reference:
"""


@dataclass
class Usage:
    input: int = 0
    cache_read: int = 0
    cache_write: int = 0
    output: int = 0

    def add(self, usage) -> None:
        self.input += usage.input_tokens or 0
        self.cache_read += usage.cache_read_input_tokens or 0
        self.cache_write += usage.cache_creation_input_tokens or 0
        self.output += usage.output_tokens or 0

    def __str__(self) -> str:
        total_in = self.input + self.cache_read + self.cache_write
        return f"in {total_in:,} (cached {self.cache_read:,}) · out {self.output:,}"


class AssistantError(Exception):
    pass


TextHandler = Callable[[str], Awaitable[None] | None]
ToolHandler = Callable[[str, dict, str, bool], Awaitable[None] | None]


async def _call(handler, *args) -> None:
    result = handler(*args)
    if hasattr(result, "__await__"):
        await result


class Assistant:
    def __init__(self, workspace: Workspace, model: str = DEFAULT_MODEL, effort: str = DEFAULT_EFFORT):
        self.workspace = workspace
        self.model = model
        self.effort = effort
        self.messages: list[dict] = []
        self.usage = Usage()
        self._system: list[dict] | None = None
        self._described_source = None
        self._client: anthropic.AsyncAnthropic | None = None

    def reset(self) -> None:
        self.messages.clear()
        self._system = None
        self._described_source = None

    def _source_text(self) -> str:
        ws = self.workspace
        if ws.source is None:
            return "No model is loaded yet."
        return "Loaded model summary:\n" + ws.extractor.describe(ws.source)

    def _start(self) -> list[dict]:
        """System prompt for a new conversation, frozen for its whole length."""
        ws = self.workspace
        self._described_source = ws.source
        return [
            {"type": "text", "text": INSTRUCTIONS + ws.extractor.language_help},
            {"type": "text", "text": self._source_text(), "cache_control": {"type": "ephemeral"}},
        ]

    def _request(self) -> dict:
        params = dict(
            model=self.model,
            max_tokens=16000,
            system=self._system,
            tools=TOOLS,
            messages=self.messages,
            cache_control={"type": "ephemeral"},  # also cache the conversation up to its last block
            output_config={"effort": self.effort},
        )
        if self.model in _FALLBACK_MODELS:
            # If a safety classifier declines, the API retries on Anthropic's recommended fallback model.
            params["betas"] = ["server-side-fallback-2026-07-01"]
            params["fallbacks"] = "default"
        return params

    async def send(self, text: str, on_text: TextHandler, on_tool: ToolHandler) -> None:
        """Send a user message and run tool calls until Claude answers."""
        if self._client is None:
            try:
                client = anthropic.AsyncAnthropic()
            except anthropic.AnthropicError:
                raise AssistantError(NO_CREDENTIALS) from None
            # API key, auth token, or an `ant auth login` profile (held in the client's token cache).
            if not (getattr(client, "api_key", None) or getattr(client, "auth_token", None)
                    or getattr(client, "_token_cache", None)):
                raise AssistantError(NO_CREDENTIALS)
            self._client = client
        if self._system is None:
            self._system = self._start()
        start = len(self.messages)
        described = self._described_source
        self.messages.append({"role": "user", "content": text})
        if self.workspace.source is not self._described_source:
            self._described_source = self.workspace.source
            self.messages.append({"role": "system", "content": "The user changed the model. " + self._source_text()})
        try:
            await self._run(on_text, on_tool)
        except BaseException:  # API errors, a stop by the user (cancellation), ...
            # Drop the unfinished turn so the history stays valid for the next message.
            del self.messages[start:]
            self._described_source = described
            raise

    async def _run(self, on_text: TextHandler, on_tool: ToolHandler) -> None:
        json_retries = 0
        for _ in range(MAX_TOOL_ROUNDS):
            try:
                async with self._client.beta.messages.stream(**self._request()) as stream:
                    async for event in stream:
                        if event.type == "text":
                            await _call(on_text, event.text)
                    message = await stream.get_final_message()
            except ValueError:
                # Tool input JSON the SDK could not parse (eager input streaming); ask again.
                json_retries += 1
                if json_retries > 2:
                    raise AssistantError("Claude produced an invalid tool call several times.") from None
                continue
            except anthropic.AuthenticationError:
                raise AssistantError(NO_CREDENTIALS) from None
            except anthropic.RateLimitError:
                raise AssistantError("Rate limited by the API; wait a moment and try again.") from None
            except anthropic.APIConnectionError:
                raise AssistantError("Could not reach the Anthropic API.") from None
            except anthropic.APIStatusError as err:
                raise AssistantError(f"API error {err.status_code}: {err.message}") from None
            except anthropic.AnthropicError as err:  # e.g. no credentials found when sending
                raise AssistantError(f"{NO_CREDENTIALS} ({err})") from None
            json_retries = 0

            self.usage.add(message.usage)
            self.messages.append({"role": "assistant", "content": message.content})
            if message.stop_reason == "refusal":
                await _call(on_text, "\n\n_(The request was declined.)_")
                return
            if message.stop_reason == "pause_turn":
                continue
            tool_uses = [b for b in message.content if b.type == "tool_use"]
            if not tool_uses:
                return

            results = []
            for block in tool_uses:
                if message.stop_reason == "max_tokens":
                    content, is_error = "Your output was cut off before this call was complete; try again.", True
                else:
                    content, is_error = run_tool(self.workspace, block.name, block.input)
                    await _call(on_tool, block.name, block.input, content, is_error)
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": content, "is_error": is_error})
            self.messages.append({"role": "user", "content": results})
        await _call(on_text, "\n\n_(Stopped after too many tool calls.)_")
