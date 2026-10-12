// IFCQuery editor: CodeMirror 6 with highlighting, and with linting and
// completion answered by Python (see query_editor.py).
import * as CM from "ifcq-codemirror";

const KEYWORDS = new Set(["let", "and", "or", "not", "in", "exists", "true", "false"]);
const FUNCTIONS = new Set(["count", "sum", "avg", "min", "max", "first"]);

const language = CM.StreamLanguage.define({
  name: "ifcquery",
  token(stream) {
    if (stream.eatSpace()) return null;
    const prev = stream.pos > 0 ? stream.string[stream.pos - 1] : "";
    if (stream.match("//")) {
      stream.skipToEnd();
      return "comment";
    }
    if (stream.match(/^"(?:[^"\\]|\\.)*"?/)) {
      if (stream.peek() === ".") return "namespace";
      return prev === "." ? "propertyName" : "string";
    }
    if (stream.match(/^\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/)) return "number";
    if (stream.match(/^(?:->|~=|!=|<=|>=|[=<>+\-*/])/)) return "operator";
    if (stream.match(/^[\p{L}_][\p{L}\p{N}_]*/u)) {
      const word = stream.current();
      const lower = word.toLowerCase();
      if (lower.startsWith("ifc")) return "typeName";
      if (KEYWORDS.has(lower)) return "keyword";
      if (FUNCTIONS.has(lower)) return "variableName.function";
      if (stream.peek() === ".") return "namespace";
      if (prev === ".") return "propertyName";
      if (/^[A-Z][A-Z0-9_]+$/.test(word)) return "atom";
      return "variableName";
    }
    stream.next();
    return null;
  },
  languageData: { commentTokens: { line: "//" } },
});

// Dark palette matching theme.py (nicegui.io colours).
const C = {
  panel: "#1e222c", surface: "#181b23", text: "#edeff3", dim: "#9ba2ae", muted: "#6b737e",
  border: "rgba(255,255,255,0.08)", blue: "#5898d4", blueLight: "#7ab4e4", accent: "#f0a050",
};
const MONO = "'Fira Mono', ui-monospace, Consolas, monospace";

const highlight = CM.HighlightStyle.define([
  { tag: CM.tags.typeName, color: C.blueLight, fontWeight: "500" },
  { tag: CM.tags.keyword, color: "#c792ea" },
  { tag: CM.tags.function(CM.tags.variableName), color: C.accent },
  { tag: CM.tags.string, color: "#a6d189" },
  { tag: CM.tags.number, color: "#f78c6c" },
  { tag: CM.tags.atom, color: "#e5c07b" },
  { tag: CM.tags.namespace, color: "#5fcfcf" },
  { tag: CM.tags.propertyName, color: "#89ddff" },
  { tag: CM.tags.operator, color: "#f07178" },
  { tag: CM.tags.variableName, color: C.text },
  { tag: CM.tags.comment, color: C.muted, fontStyle: "italic" },
]);

const theme = CM.EditorView.theme({
  "&": {
    fontSize: "14px", color: C.text, background: C.panel,
    border: `1px solid ${C.border}`, borderRadius: "8px",
    transition: "border-color 0.15s, box-shadow 0.15s",
  },
  "&.cm-focused": { outline: "none", borderColor: C.blue, boxShadow: `0 0 0 3px rgba(88,152,212,0.18)` },
  ".cm-content": {
    fontFamily: MONO,
    fontVariantLigatures: "none",  // show "->" as typed, not as an arrow
    padding: "8px 0",
    minHeight: "2.6em",
    caretColor: C.blueLight,
  },
  ".cm-line": { padding: "0 10px" },
  ".cm-cursor, .cm-dropCursor": { borderLeftColor: C.blueLight },
  "&.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground, .cm-selectionBackground, ::selection":
    { background: "rgba(88,152,212,0.30)" },
  ".cm-placeholder": { color: C.muted },
  ".cm-matchingBracket, &.cm-focused .cm-matchingBracket": { background: "rgba(240,160,80,0.18)", outline: "none" },
  ".cm-tooltip": {
    background: C.surface, color: C.text, border: `1px solid ${C.border}`, borderRadius: "8px",
    boxShadow: "0 8px 24px rgba(0,0,0,0.45)", overflow: "hidden",
  },
  ".cm-tooltip.cm-tooltip-autocomplete > ul": { fontFamily: MONO, maxHeight: "18em" },
  ".cm-tooltip-autocomplete ul li[aria-selected]": { background: "rgba(88,152,212,0.25)", color: C.text },
  ".cm-completionIcon": { color: C.dim, opacity: "0.9" },
  ".cm-completionMatchedText": { textDecoration: "none", color: C.accent },
  ".cm-completionDetail": { marginLeft: "1em", color: C.muted, fontStyle: "normal" },
  ".cm-completionInfo": { background: C.surface, color: C.dim },
  ".cm-diagnostic": { padding: "6px 10px", fontFamily: "Inter, system-ui, sans-serif", fontSize: "13px" },
  ".cm-diagnostic-error": { borderLeftColor: "#ef6b73" },
  ".cm-diagnostic-warning": { borderLeftColor: C.accent },
  ".cm-diagnostic-info": { borderLeftColor: C.blue },
}, { dark: true });

// Words the completion list keeps filtering locally while the user types.
// A "." or "(" ends the word, so the next request asks for what follows it.
const VALID_FOR = /^(?:"[^"\n]*"?|[\p{L}\p{N}_]*)$/u;
// After these, completion opens without typing a letter first.
const OPENS_COMPLETION = /(?:[.[(,=<>]|->|~=|\b(?:and|or|not|in))\s*$/i;

function toCompletion(option) {
  const completion = {
    label: option.label,
    type: option.type,
    detail: option.detail,
    info: option.info,
    boost: option.boost,
  };
  if (option.retrigger) {
    completion.apply = (view, c, from, to) => {
      view.dispatch(CM.insertCompletionText(view.state, c.label, from, to));
      setTimeout(() => CM.startCompletion(view), 0);
    };
  }
  return completion;
}

export default {
  template: "<div></div>",
  props: {
    value: String,
    placeholder: String,
    readonly: Boolean,
  },
  mounted() {
    this.requests = new Map();
    this.nextRequest = 1;
    this.sent = this.value || "";

    const completionSource = async (context) => {
      const word = context.matchBefore(/(?:"[^"\n]*|[\p{L}\p{N}_]+)$/u);
      if (!context.explicit && !word) {
        const before = context.state.sliceDoc(Math.max(0, context.pos - 8), context.pos);
        if (!OPENS_COMPLETION.test(before)) return null;
      }
      const text = context.state.doc.toString();
      const result = await this.request("complete", { text, pos: context.pos });
      if (!result || context.aborted) return null;
      return { from: result.from, options: result.options.map(toCompletion), validFor: VALID_FOR };
    };

    const lintSource = async (view) => {
      const text = view.state.doc.toString();
      const diagnostics = (await this.request("lint", { text })) || [];
      if (view.state.doc.toString() !== text) return [];  // outdated; the next run replaces it
      const length = text.length;
      return diagnostics.map((d) => ({
        from: Math.min(d.from, length),
        to: Math.min(Math.max(d.to, d.from), length),
        severity: d.severity,
        message: d.message,
      }));
    };

    let changeTimer = null;
    const emitChange = () => {
      clearTimeout(changeTimer);
      const text = this.view.state.doc.toString();
      if (text === this.sent) return;
      this.sent = text;
      this.$emit("change", text);
    };

    this.readonlyCompartment = new CM.Compartment();
    this.view = new CM.EditorView({
      parent: this.$el,
      doc: this.value || "",
      extensions: [
        CM.history(),
        CM.drawSelection(),
        CM.bracketMatching(),
        CM.closeBrackets(),
        CM.EditorView.lineWrapping,
        CM.placeholder(this.placeholder || ""),
        language,
        CM.syntaxHighlighting(highlight),
        theme,
        CM.autocompletion({ override: [completionSource], icons: false, activateOnTypingDelay: 60 }),
        CM.linter(lintSource, { delay: 250 }),
        this.readonlyCompartment.of(CM.EditorState.readOnly.of(!!this.readonly)),
        CM.keymap.of([
          { key: "Mod-Enter", run: () => { emitChange(); this.$emit("run"); return true; } },
          ...CM.closeBracketsKeymap,
          ...CM.completionKeymap,
          ...CM.defaultKeymap,
          ...CM.historyKeymap,
          ...CM.lintKeymap,
        ]),
        CM.EditorView.updateListener.of((update) => {
          if (update.docChanged) {
            clearTimeout(changeTimer);
            changeTimer = setTimeout(emitChange, 300);
          }
          if (update.focusChanged && !update.view.hasFocus) emitChange();
        }),
      ],
    });
  },
  beforeUnmount() {
    this.view?.destroy();
    for (const resolve of this.requests.values()) resolve(null);
  },
  watch: {
    value(text) {
      // Text set from Python (proposal accepted, file loaded). Ignore echoes of what we sent.
      const current = this.view.state.doc.toString();
      if (text === current || (text === this.sent && this.view.hasFocus)) return;
      this.sent = text;
      this.view.dispatch({ changes: { from: 0, to: current.length, insert: text || "" } });
    },
    readonly(flag) {
      this.view.dispatch({ effects: this.readonlyCompartment.reconfigure(CM.EditorState.readOnly.of(!!flag)) });
    },
  },
  methods: {
    request(kind, payload) {
      const id = this.nextRequest++;
      return new Promise((resolve) => {
        this.requests.set(id, resolve);
        this.$emit("request", { id, kind, ...payload });
        setTimeout(() => this.resolve(id, null), 5000);
      });
    },
    resolve(id, result) {
      const resolve = this.requests.get(id);
      if (resolve) {
        this.requests.delete(id);
        resolve(result);
      }
    },
    relint() {
      CM.forceLinting(this.view);
    },
    focus() {
      this.view.focus();
    },
  },
};
