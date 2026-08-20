from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.pending import start_session, package, PENDING

app = FastAPI()


class AskQuestion(BaseModel):
    question: str


class ConfirmDecision(BaseModel):
    id: str
    approved: bool

@app.post("/ask")
def ask(req: AskQuestion):
    """Start a run. Returns either the final answer, or a pending action
    the client must approve/deny via /confirm."""
    s = start_session(req.question)
    return package(s)


@app.post("/confirm")
def confirm(req: ConfirmDecision):
    """Deliver a decision to a parked run and let it resume. May return the
    final answer, OR another needs_confirmation if the run hits a second write."""
    s = PENDING.get(req.id)
    if s is None:
        raise HTTPException(404, "no such pending confirmation (expired or already resumed)")
    if s.done:
        return package(s)
    s.provide_decision(req.approved)
    s.wait_until_paused_or_done()   # resume, then wait for the next stop
    return package(s)


