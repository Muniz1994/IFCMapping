"""A query text box with IFCQuery syntax highlighting (Streamlit components v2).

A transparent <textarea> sits on top of a <pre> that shows the highlighted
text; both share one grid cell, so the box grows with its content. The text is
sent to Python on blur or Ctrl/Cmd+Enter, like ``st.text_area``.
"""
from __future__ import annotations

import functools

import streamlit as st

CSS = """
.ifcq {
  display: grid;
  border: 1px solid var(--st-border-color, rgba(128, 128, 128, 0.35));
  border-radius: var(--st-base-radius, 0.5rem);
  background: var(--st-secondary-background-color, #f0f2f6);
  color: var(--st-text-color, #31333f);
}
.ifcq:focus-within { border-color: var(--st-primary-color, #ff4b4b); }
.ifcq pre, .ifcq textarea {
  grid-area: 1 / 1;
  margin: 0;
  padding: 0.6rem 0.75rem;
  border: 0;
  min-height: 4.5em;
  font-family: var(--st-code-font, "Source Code Pro", ui-monospace, monospace);
  font-size: 14px;
  line-height: 1.5;
  tab-size: 4;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  box-sizing: border-box;
}
.ifcq pre { pointer-events: none; }
.ifcq textarea {
  width: 100%;
  height: 100%;
  resize: none;
  overflow: hidden;
  outline: none;
  background: transparent;
  color: transparent;
  caret-color: var(--st-text-color, #31333f);
}
.ifcq textarea::placeholder { color: var(--st-text-color, #31333f); opacity: 0.45; }
.ifcq textarea::selection { background: rgba(80, 140, 230, 0.35); }
.t-cls  { color: #2b8fd6; }
.t-kw   { color: #b05fd6; }
.t-fn   { color: #d97a1f; }
.t-str  { color: #3a9a4a; }
.t-num  { color: #d14d72; }
.t-enum { color: #c99a1e; }
.t-pset { color: #13a3a3; }
.t-prop { color: #3c8c8c; }
.t-op   { color: #e0605a; }
.t-cmt  { color: #8a8f98; }
"""

JS = r"""
const KEYWORDS = new Set(["let", "and", "or", "not", "in", "exists", "true", "false"]);
const AGGREGATES = new Set(["count", "sum", "avg", "min", "max", "first"]);
const TOKEN = /(\/\/[^\n]*)|("(?:[^"\\\n]|\\.)*"?)|(\d+(?:\.\d+)?)|(->|~=|!=|<=|>=|[=<>+\-*\/])|([A-Za-z_À-ɏ][\wÀ-ɏ]*)/g;

const escape = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const span = (cls, s) => `<span class="t-${cls}">${escape(s)}</span>`;

function highlight(text) {
  let out = "", last = 0, m;
  TOKEN.lastIndex = 0;
  while ((m = TOKEN.exec(text))) {
    out += escape(text.slice(last, m.index));
    last = TOKEN.lastIndex;
    const [tok, cmt, str, num, op, word] = m;
    if (cmt) out += span("cmt", tok);
    else if (str) out += span(text[last] === "." ? "pset" : text[m.index - 1] === "." ? "prop" : "str", tok);
    else if (num) out += span("num", tok);
    else if (op) out += span("op", tok);
    else {
      const lower = word.toLowerCase();
      let cls;
      if (lower.startsWith("ifc")) cls = "cls";
      else if (KEYWORDS.has(lower)) cls = "kw";
      else if (AGGREGATES.has(lower)) cls = "fn";
      else if (text[last] === ".") cls = "pset";
      else if (text[m.index - 1] === ".") cls = "prop";
      else if (/^[A-Z][A-Z0-9_]+$/.test(word)) cls = "enum";
      out += cls ? span(cls, tok) : escape(tok);
    }
  }
  out += escape(text.slice(last));
  // A trailing newline needs content after it to keep its line height.
  return out + (text.endsWith("\n") || text === "" ? " " : "");
}

export default function ({ parentElement, data, setStateValue }) {
  let root = parentElement.querySelector(".ifcq");
  if (!root) {
    root = document.createElement("div");
    root.className = "ifcq";
    const pre = document.createElement("pre");
    pre.setAttribute("aria-hidden", "true");
    const ta = document.createElement("textarea");
    ta.spellcheck = false;
    ta.setAttribute("autocomplete", "off");
    ta.setAttribute("autocapitalize", "off");
    root.append(pre, ta);
    parentElement.appendChild(root);

    const state = { ta, pre, focused: false, committed: null, received: null, send: setStateValue };
    root._ifcq = state;
    const render = () => { pre.innerHTML = highlight(ta.value); };
    const commit = () => {
      if (ta.value !== state.committed) {
        state.committed = ta.value;
        state.send("value", ta.value);
      }
    };
    state.render = render;
    ta.addEventListener("input", render);
    ta.addEventListener("focus", () => { state.focused = true; });
    ta.addEventListener("blur", () => { state.focused = false; commit(); });
    ta.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); commit(); }
    });
  }

  const state = root._ifcq;
  state.send = setStateValue;
  state.ta.placeholder = data?.placeholder ?? "";
  const incoming = data?.value ?? "";
  // Take text from Python only when it changed there (e.g. queries uploaded),
  // and never while the user is typing.
  if (incoming !== state.received) {
    state.received = incoming;
    if (!state.focused) {
      state.ta.value = incoming;
      state.committed = incoming;
      state.render();
    }
  }
}
"""

_component = st.components.v2.component("ifcquery_editor", css=CSS, js=JS)


def _sync(state_key: str, editor_key: str) -> None:
    editor_state = st.session_state.get(editor_key) or {}
    value = editor_state.get("value") if hasattr(editor_state, "get") else getattr(editor_state, "value", None)
    st.session_state[state_key] = value or ""


def query_editor(state_key: str, *, key: str, placeholder: str = "") -> None:
    """Edit the query held in ``st.session_state[state_key]``."""
    _component(
        key=key,
        data={"value": st.session_state.get(state_key, ""), "placeholder": placeholder},
        default={"value": None},
        on_value_change=functools.partial(_sync, state_key, key),
    )
