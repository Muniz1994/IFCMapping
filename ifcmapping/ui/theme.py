"""Dark theme, after the NiceGUI website (nicegui.io): its palette, Inter and Fira Mono."""
from __future__ import annotations

from nicegui import ui

BLUE = "#5898d4"
BLUE_LIGHT = "#7ab4e4"
ACCENT = "#f0a050"
BG = "#0f1117"
SURFACE = "#181b23"
PANEL = "#1e222c"            # code, editors, chat bubbles
TEXT = "#edeff3"
TEXT_DIM = "#9ba2ae"
TEXT_MUTED = "#6b737e"
BORDER = "rgba(255,255,255,0.08)"
GREEN = "#5cc58a"
RED = "#ef6b73"

FONTS = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fira+Mono:wght@400;500&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
"""

CSS = f"""
:root {{ --ifcm-border: {BORDER}; }}
html, body, body.body--dark {{ background: {BG}; color: {TEXT}; }}
body {{ font-family: Inter, system-ui, -apple-system, sans-serif; -webkit-font-smoothing: antialiased; }}
.text-mono, code, pre, .q-badge.text-mono {{ font-family: "Fira Mono", ui-monospace, Consolas, monospace; }}

/* Header: translucent surface with blur, hairline border (as on nicegui.io when scrolled). */
.q-header.ifcm-header {{
  background: color-mix(in srgb, {SURFACE} 80%, transparent);
  backdrop-filter: blur(12px);
  box-shadow: 0 1px 0 {BORDER};
  color: {TEXT};
}}
.ifcm-brand {{
  font-weight: 700; letter-spacing: -0.02em;
  background: linear-gradient(90deg, {BLUE_LIGHT}, {ACCENT});
  -webkit-background-clip: text; background-clip: text; color: transparent;
}}

/* Surfaces */
.q-drawer {{ background: {SURFACE} !important; }}
.q-drawer--right.q-drawer--bordered {{ border-left: 1px solid {BORDER} !important; }}
.q-card.ifcm-card {{
  background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; box-shadow: none;
  transition: border-color 0.15s;
}}
.q-card.ifcm-card:hover, .q-card.ifcm-card:focus-within {{ border-color: color-mix(in srgb, {BLUE} 45%, transparent); }}
.q-dialog .q-card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 14px; }}
.q-card.ifcm-proposal {{
  background: color-mix(in srgb, {BLUE} 10%, {SURFACE}); border: 1px solid color-mix(in srgb, {BLUE} 35%, transparent);
  border-radius: 10px; box-shadow: none;
}}
.ifcm-panel {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 12px; }}
.q-table__card, .q-table--dark {{ background: {SURFACE}; border-color: {BORDER} !important; }}
.q-tab-panels {{ background: transparent !important; }}
.q-tabs {{ color: {TEXT_DIM}; }}
.q-tab--active {{ color: {TEXT}; }}
.q-field--outlined .q-field__control:before {{ border-color: {BORDER}; }}
.q-uploader {{ background: {PANEL}; }}

/* Text */
.ifcm-dim {{ color: {TEXT_DIM}; }}
.ifcm-muted {{ color: {TEXT_MUTED}; }}
.nicegui-markdown a {{ color: {BLUE}; }}

/* Chat */
.ifcm-chat .q-message-name {{ color: {TEXT_MUTED}; }}
.ifcm-chat .q-message-text {{ border-radius: 12px; }}
.ifcm-chat .q-message-text:last-child:before {{ display: none; }}

/* Scrollbars */
* {{ scrollbar-color: rgba(255,255,255,0.15) transparent; scrollbar-width: thin; }}
"""


def apply() -> None:
    """Call once per page, before building it."""
    ui.dark_mode(True)
    ui.colors(primary=BLUE, secondary=BLUE_LIGHT, accent=ACCENT, dark=SURFACE, dark_page=BG,
              positive=GREEN, negative=RED, info=BLUE_LIGHT, warning=ACCENT,
              panel=PANEL, ink=TEXT)
    ui.add_head_html(FONTS)
    ui.add_css(CSS)
