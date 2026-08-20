"""Suspend/resume for confirmation-gated agent runs over stateless HTTP.

The problem: an HTTP request can't block for minutes while a human decides,
and the write we're gating lives two agents deep inside run_supervisor. We
can't cheaply serialize that nested state.

The solution: run the agent on a WORKER THREAD and PARK it. When the run hits
a state-changing tool, its confirm_fn (running on the worker) blocks on an
event. The worker's live call stack holds ALL nested state for free. The HTTP
handler, meanwhile, waits on a SEPARATE event ("paused or done?") and returns
as soon as the worker either needs a decision or finishes.

Two threads, two events, one handshake:
    worker  --_paused.set()-->   handler   ("I need a decision" / "I'm done")
    handler --_decision.set()--> worker    ("here's the decision")
"""


import threading
import uuid

from app.multiagent import run_supervisor

CONFIRM_TIMEOUT = 300.0   # seconds

class Session:
    def __init__(self, question: str):
        self.id = uuid.uuid4().hex[:8]
        self.question = question

        # worker -> handler: "I've paused for a decision, or I've finished."
        self._paused = threading.Event()
        # handler -> worker: "the decision is set; you may proceed."
        self._decision = threading.Event()

        self.pending: dict | None = None   # {tool, args} while parked at a write
        self.approved: bool | None = None  # set by the /confirm handler
        self.answer: str | None = None     # final answer when done
        self.error: str | None = None
        self.done = False

    # --- runs ON the worker thread, deep inside the store agent's dispatch ---
    def confirm_fn(self, name: str, args: dict) -> bool:
        """The gate calls this synchronously. We record the pending action,
        wake the waiting HTTP handler, then BLOCK until a decision arrives."""
        self.pending = {"tool": name, "args": args}
        self.approved = None
        self._decision.clear()      # clear BEFORE signalling, so a decision
        self._paused.set()          # from this round can't be missed
        got = self._decision.wait(timeout=CONFIRM_TIMEOUT)
        self.pending = None
        if not got:
            return False            # timed out -> fail closed
        return bool(self.approved)

    def _run(self):
        try:
            # confirm_fn is threaded all the way down to cancel_order's gate.
            self.answer = run_supervisor(self.question, confirm_fn=self.confirm_fn)
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
        finally:
            self.done = True
            self._paused.set()      # final wake: "I'm finished."


    def start(self):
        # daemon: don't keep the process alive on shutdown for a parked run.
        threading.Thread(target=self._run, daemon=True).start()

    # --- called ON the HTTP handler thread ---
    def wait_until_paused_or_done(self):
        self._paused.wait()
        self._paused.clear()

    def provide_decision(self, approved: bool):
        self.approved = approved
        self._decision.set()



PENDING: dict[str, Session] = {}

def start_session(question: str) -> Session:
    s = Session(question)
    PENDING[s.id] = s
    s.start()
    s.wait_until_paused_or_done()   # block until it needs us or finishes
    return s



def package(s: Session) -> dict:
    """Render a session's current state as an HTTP response dict."""
    if not s.done:
        return {"status": "needs_confirmation", "id": s.id, "action": s.pending}
    PENDING.pop(s.id, None)         # finished -> clean up
    if s.error:
        return {"status": "error", "error": s.error}
    return {"status": "done", "answer": s.answer}




