"""Regulatory document drafts (SAR enrichment helpers + PBRER/PSUR + SJL).

Heavy imports are lazy so lightweight modules (e.g. inspection_audit) remain
importable in offline unit tests without SQLAlchemy.
"""

__all__ = [
    "build_pbrer_payload",
    "render_pbrer_markdown",
    "render_pbrer_pdf",
    "render_docx_or_markdown",
]


def __getattr__(name: str):
    if name in ("build_pbrer_payload", "render_pbrer_markdown", "render_pbrer_pdf"):
        from . import pbrer

        return getattr(pbrer, name)
    if name == "render_docx_or_markdown":
        from . import docx_pdf_generator

        return getattr(docx_pdf_generator, name)
    raise AttributeError(name)
