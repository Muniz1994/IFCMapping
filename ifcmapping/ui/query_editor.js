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

const highlight = CM.HighlightStyle.define([
  { tag: CM.tags.typeName, color: "#1f7fc4" },
  { tag: CM.tags.keyword, color: "#9a4fc4" },
  { tag: CM.tags.function(CM.tags.variableName), color: "#c96a10" },
  { tag: CM.tags.string, color: "#2f8a3e" },
  { tag: CM.tags.number, color: "#c23f66" },
  { tag: CM.tags.atom, color: "#a8800c" },
  { tag: CM.tags.namespace, color: "#0f8f8f" },
  { tag: CM.tags.propertyName, color: "#2f7a7a" },
  { tag: CM.tags.operator, color: "#d2504a" },
  { tag: CM.tags.comment, color: "#8a8f98", fontStyle: "italic" },
]);

const theme = CM.EditorView.theme({
  "&": { fontSize: "14px", border: "1px solid #d0d4da", borderRadius: "6px", background: "#fbfcfd" },
  "&.cm-focused": { outline: "none", borderColor: "#1976d2" },
  ".cm-content": {
    fontFamily: "ui-monospace, 'Cascadia Code', Consolas, monospace",
    fontVariantLigatures: "none",  // show "->" as typed, not as an arrow
    padding: "6px 0",
    minHeight: "2.6em",
  },
  ".cm-line": { padding: "0 8px" },
  ".cm-tooltip.cm-tooltip-autocomplete > ul": { fontFamily: "ui-monospace, 'Cascadia Code', Consolas, monospace" },
  ".cm-completionDetail": { marginLeft: "1em", color: "#8a8f98", fontStyle: "normal" },
});

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
        CM.autocompletion({ override: [completionSource], icons: true, activateOnTypingDelay: 60 }),
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
