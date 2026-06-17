"""Shared report styling — one project standard for notebook tables (and charts).

Centralised so every notebook looks the same and a single edit re-themes them all.

`NOTEBOOK_TABLE_CSS` is a high-contrast, **print-friendly**, theme-independent
theme for pandas `DataFrame` display: a dark slate header with white text (reads
well in light *or* dark IDE themes), a white body with near-black text, zebra
striping, and thin borders. No third-party dependency — it styles the
`table.dataframe` markup pandas already emits, so existing `display(df)` calls
just work once the CSS is shown once at the top of a notebook.
"""
from __future__ import annotations

# Palette
_HEADER_BG = "#37474F"   # dark slate
_HEADER_FG = "#FFFFFF"   # white  -> ~9:1 contrast on the slate (WCAG AAA)
_BODY_FG = "#1A1A1A"
_BORDER = "#CFD8DC"
_ZEBRA = "#F4F6F7"
_HOVER = "#E3F2FD"

NOTEBOOK_TABLE_CSS = f"""
<style>
table.dataframe {{
  background-color: #FFFFFF !important;
  color: {_BODY_FG} !important;
  border-collapse: collapse !important;
  border: 1px solid #B0BEC5 !important;
  font-size: 0.92em !important;
}}
table.dataframe thead th {{
  background-color: {_HEADER_BG} !important;
  color: {_HEADER_FG} !important;
  font-weight: 700 !important;
  border: 1px solid {_HEADER_BG} !important;
  padding: 5px 9px !important;
  text-align: right !important;
}}
table.dataframe td, table.dataframe th {{
  border: 1px solid {_BORDER} !important;
  padding: 4px 9px !important;
}}
table.dataframe tbody tr:nth-child(even) td {{
  background-color: {_ZEBRA} !important;
}}
table.dataframe tbody tr:hover td {{
  background-color: {_HOVER} !important;
}}
</style>
"""


def show_table_style():
    """Display the standard table CSS in a notebook (call once in the setup cell)."""
    from IPython.display import HTML, display
    display(HTML(NOTEBOOK_TABLE_CSS))
