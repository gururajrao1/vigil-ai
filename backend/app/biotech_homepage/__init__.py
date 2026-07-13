"""Schema-driven biotech product homepage — editorial narrative canvas.

Stitch MCP = design-time screens. FastMCP ``render_biotech_homepage`` = runtime
JSON website map. React paints sections — never admin grids or spreadsheet UIs.
"""

from .layout_engine import render_biotech_homepage

__all__ = ["render_biotech_homepage"]
