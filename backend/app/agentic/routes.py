"""Agentic forum-onboarding + MCP-lite chat crawl dispatch API."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import require_role
from ..database import get_db
from ..pipeline import ingest_posts, recompute_signals
from .chat_dispatch import dispatch as chat_dispatch
from .forum_onboarding import onboard_forum

router = APIRouter(prefix="/api/agentic", tags=["agentic"])


class OnboardReq(BaseModel):
    url: str
    ingest: bool = False


class ChatReq(BaseModel):
    message: str
    execute: bool = True


@router.post("/onboard-forum")
def onboard(req: OnboardReq, db: Session = Depends(get_db),
            _user=Depends(require_role("analyst"))):
    """Analyze a forum URL; optionally ingest scrubbed sample posts into VigilAI."""
    cfg = onboard_forum(req.url)
    ingested = 0
    if req.ingest and cfg.get("sample_posts"):
        posts = []
        for i, sample in enumerate(cfg["sample_posts"]):
            content = (sample.get("content") or "").strip()
            if len(content) < 40:
                continue
            posts.append({
                "external_id": f"forum_onboard_{hash(req.url) & 0xffffffff}_{i}",
                "platform": "forum",
                "url": req.url,
                "author": f"onboard_{i}",
                "title": (cfg.get("forum_type") or "forum")[:120],
                "body": content[:4000],
                "region": "Global",
            })
        if posts:
            ingested = ingest_posts(db, posts, use_transformer=False,
                                    use_presidio=False, online_translation=False)
            recompute_signals(db, use_fda=False, with_narrative=False)
    return {**cfg, "ingested": ingested, "ingest_requested": req.ingest}


@router.post("/chat")
def agent_chat(req: ChatReq, db: Session = Depends(get_db),
               _user=Depends(require_role("analyst"))):
    """Conversational crawl dispatcher (Algo-Pharma MCP-lite equivalent).

    Always returns a JSON payload — crawl/parse failures are soft errors in the
    reply body so the Agent chat UI never sees a bare 500 for bad prompts.
    """
    try:
        return chat_dispatch(db, req.message or "", execute=req.execute)
    except Exception as exc:  # last-resort guard
        return {
            "status": "error",
            "parsed": {"slots": {}, "raw": req.message, "mode": "error"},
            "fetched": 0,
            "ingested": 0,
            "reply": f"Agent error ({type(exc).__name__}: {exc}). Try `help` or `fetch google news about ozempic`.",
        }
