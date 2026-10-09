"""Assistant tools and the tool loop, with a fake API client (no network)."""
import asyncio
import copy
from types import SimpleNamespace as NS

import pytest

from ifcmapping.assistant import Assistant, AssistantError, Workspace, run_tool
from ifcmapping.extractors.ifcq import IfcQueryExtractor
from ifcmapping.mapping import MappingSet, Parameter


@pytest.fixture
def ws():
    mapping = MappingSet(parameters=[
        Parameter("01.m2", "Superfície total", "m2", "FIRST(IfcSite -> PTMU_Licenciamento.SuperficieTotal)"),
        Parameter("06.m2", "Área bruta", "m2"),
        Parameter("11", "Pisos", None, "COUNT(IfcSpace[name = 1])"),
    ])
    return Workspace(mapping, IfcQueryExtractor("IFC4"))


# --------------------------------------------------------------------------- tools

def test_list_parameters(ws):
    text, is_error = run_tool(ws, "list_parameters", {})
    assert not is_error
    lines = text.splitlines()
    assert lines[0] == "01.m2 | Superfície total [m2] | ok | FIRST(IfcSite -> PTMU_Licenciamento.SuperficieTotal)"
    assert lines[1] == "06.m2 | Área bruta [m2] | empty | -"
    assert "| error |" in lines[2]
    assert run_tool(ws, "list_parameters", {"only_empty": True})[0] == "06.m2 | Área bruta [m2] | empty | -"


def test_get_parameters_with_model(ws, source):
    ws.source = source
    text, _ = run_tool(ws, "get_parameters", {"ids": ["01.m2", "nope"]})
    assert "value: 2000" in text
    assert "nope: no such parameter" in text


def test_check_query(ws, source):
    assert run_tool(ws, "check_query", {"query": "COUNT(IfcSpace)"})[0] == "no problems"
    ws.source = source
    assert "value: 2" in run_tool(ws, "check_query", {"query": "COUNT(IfcSpace)"})[0]
    assert "error" in run_tool(ws, "check_query", {"query": "COUNT(IfcSpace"})[0]


def test_propose_query(ws, source):
    ws.source = source
    seen = []
    ws.on_proposal = seen.append
    text, is_error = run_tool(ws, "propose_query", {
        "param_id": "06.m2", "query": "SUM(IfcSpace -> Qto_SpaceBaseQuantities.GrossFloorArea)",
        "explanation": "Sum of gross floor areas"})
    assert not is_error and "Value: 200.5" in text
    assert seen[0].param_id == "06.m2" and seen[0].preview == "200.5"
    assert ws.mapping["06.m2"].query == ""  # unchanged until the user accepts

    text, is_error = run_tool(ws, "propose_query", {"param_id": "06.m2", "query": "SUM(IfcSpace"})
    assert is_error and "errors" in text
    assert run_tool(ws, "propose_query", {"param_id": "zz", "query": "COUNT(IfcSpace)"})[1]


def test_search_model_needs_a_model(ws):
    assert "No model" in run_tool(ws, "search_model", {"pattern": "area"})[0]


@pytest.mark.parametrize("name, args", [
    ("nope", {}), ("check_query", {}), ("check_query", {"query": 3}), ("check_query", "x"),
    ("list_parameters", {"bogus": 1}),
])
def test_run_tool_rejects_bad_input(ws, name, args):
    assert run_tool(ws, name, args)[1] is True


# --------------------------------------------------------------------------- tool loop

def usage():
    return NS(input_tokens=10, cache_read_input_tokens=100, cache_creation_input_tokens=0, output_tokens=5)


class FakeStream:
    def __init__(self, message):
        self.message = message

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        async def events():
            for block in self.message.content:
                if block.type == "text":
                    yield NS(type="text", text=block.text)
        return events()

    async def get_final_message(self):
        return self.message


class FakeClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []
        self.beta = NS(messages=NS(stream=self.stream))

    def stream(self, **params):
        self.requests.append(copy.deepcopy(params))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return FakeStream(reply)


def message(*blocks, stop_reason="end_turn"):
    return NS(content=list(blocks), stop_reason=stop_reason, usage=usage())


def test_tool_loop(ws, source):
    client = FakeClient([
        message(NS(type="tool_use", id="t1", name="list_parameters", input={"only_empty": True}),
                stop_reason="tool_use"),
        message(NS(type="text", text="06.m2 has no query.")),
    ])
    assistant = Assistant(ws, model="claude-opus-5-5")
    assistant._client = client
    texts, tools = [], []
    asyncio.run(assistant.send("What is missing?", texts.append, lambda *a: tools.append(a)))

    assert "".join(texts) == "06.m2 has no query."
    assert tools[0][0] == "list_parameters" and "06.m2" in tools[0][2]
    first, second = client.requests
    assert first["system"][1]["cache_control"] == {"type": "ephemeral"}
    assert first["system"][1]["text"] == "No model is loaded yet."
    assert first["cache_control"] == {"type": "ephemeral"}
    assert first["fallbacks"] == "default" and first["betas"] == ["server-side-fallback-2026-07-01"]
    assert all(t["eager_input_streaming"] for t in first["tools"])
    # Append-only history: the second request extends the first.
    assert second["messages"][:len(first["messages"])] == first["messages"]
    assert second["messages"][-1]["content"][0]["tool_use_id"] == "t1"
    assert second["system"] == first["system"]
    assert assistant.usage.cache_read == 200

    # Loading a model mid-conversation adds a system message instead of changing the prompt.
    ws.source = source
    client.replies.append(message(NS(type="text", text="ok")))
    asyncio.run(assistant.send("I loaded the model.", texts.append, lambda *a: None))
    third = client.requests[-1]
    assert third["system"] == first["system"]
    assert third["messages"][-1]["role"] == "system" and "IfcSpace 2" in third["messages"][-1]["content"]


def test_failed_turn_is_dropped(ws):
    import anthropic
    import httpx2

    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    error = anthropic.APIConnectionError(request=request)
    client = FakeClient([error, message(NS(type="text", text="hi"))])
    assistant = Assistant(ws, model="claude-haiku-5-5")
    assistant._client = client
    with pytest.raises(AssistantError):
        asyncio.run(assistant.send("hello", lambda t: None, lambda *a: None))
    assert assistant.messages == []
    asyncio.run(assistant.send("hello again", lambda t: None, lambda *a: None))
    assert "fallbacks" not in client.requests[-1]  # Haiku has no server-side fallback
    assert [m["role"] for m in assistant.messages] == ["user", "assistant"]
