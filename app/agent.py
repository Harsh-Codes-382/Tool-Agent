import json
from app.llm import call_model
from app.tools.registry import dispatch, TOOLS

MAX_ITERATIONS = 10        # model calls per question
MAX_OUTPUT_TOKENS = 20_000 # cumulative output budget across the whole run
MAX_REFLECT = 2

SYSTEM = "You answer questions about our store using the provided tools. Only state facts the tool results support."

REFLECT_SYSTEM = (
    "You are a strict reviewer. You are given a user's QUESTION and a DRAFT "
    "ANSWER from an assistant. Judge ONLY whether the draft completely answers "
    "the question: every part addressed, specific (no vague hedging), and not a "
    "partial or aborted answer. Do NOT rewrite it.\n"
    "Reply with ONE JSON object and nothing else:\n"
    '  {"ok": true}                        if the draft is complete, or\n'
    '  {"ok": false, "fix": "<the gap, as an instruction to fix it>"}\n'
    "Be conservative: if it answers the question, say ok. Only fail it for a "
    "real gap the assistant could close with more work."
)

def __reflect(question: str, draft: str) -> dict:
    """One independent critique pass. Returns {"ok": bool, "fix": str, "usage": ...}.

    Runs as a SEPARATE, tool-less model call with a fresh two-message context —
    not the actor's own transcript — so it's a cheap, genuinely independent check
    rather than the model rubber-stamping its own history.

    Fails OPEN: if the verdict won't parse, we treat the draft as acceptable.
    Reflection is an enhancement, never a gate that can trap a good answer
    behind a malformed critique.
    """
    review = [{
        "role": "user",
        "content": f"QUESTION:\n{question}\n\nDRAFT ANSWER:\n{draft}",
    }]
    resp = call_model(messages=review, system=REFLECT_SYSTEM)   # no tools
    text = "".join(b.text for b in resp.content if b.type == "text").strip()

    try:
        verdict = json.loads(text)
        result = {
            "ok": bool(verdict.get("ok", True)),
            "fix": str(verdict.get("fix", "")),
            "usage": resp.usage,
        }

        print(f"  [reflect] ok={result['ok']} fix={result['fix'][:60]!r}")
        return result
    except (json.JSONDecodeError, AttributeError):
        print("  [reflect] unparseable verdict → failing open (ok=True)")
        return {"ok": True, "fix": "", "usage": resp.usage}

    

def __degrade(reason: str, messages: list) -> str:
    """Stop early and hand back whatever the model already produced.

    Raising here would throw away real work — the model may have made
    three good tool calls before hitting the ceiling. Degrading returns
    the partial answer plus a machine-readable reason.
    """

    partial = ""

    for msg in reversed(messages):
        if msg["role"] != "assistant":
            continue

        # Assistant content is the raw block list from resp.content, so these
        # are SDK objects, not dicts — getattr, not ["type"].
        partial = "".join(
            b.text for b in msg["content"] if getattr(b, "type", None) == "text"
        )
        if partial:
            break

    return f"[stopped: {reason}]" + (f"\n\n{partial}" if partial else "")

def run_agent(user_que: str, *, tools=None, system=None, dispatch_fn = None, confirm_fn = None) -> str:
    messages = [{'role': "user", "content": user_que}]
    output_spent = 0
    reflect_rounds = 0

    if tools is None:
        tools = TOOLS
    if system is None:
        system = SYSTEM
    if dispatch_fn is None:
        dispatch_fn = dispatch

    

    for step in range(1, MAX_ITERATIONS+1):
        resp = call_model(messages=messages, tools=tools, system=system)

        u = resp.usage
        output_spent += u.output_tokens
        print(
            f"[{step}] in={u.input_tokens} out={u.output_tokens} "
            f"cache_w={u.cache_creation_input_tokens} "
            f"cache_r={u.cache_read_input_tokens} "
            f"stop={resp.stop_reason} spent={output_spent}"
        )

        # OUTPUT side full: the reply was cut off mid-generation.
        if resp.stop_reason == "max_tokens":
            messages.append({"role": "assistant", "content": resp.content})
            return __degrade("output truncated (raise max_tokens in llm.py)", messages)

        # INPUT side full: the conversation no longer fits the window.
        if resp.stop_reason == "model_context_window_exceeded":
            return __degrade("context window full", messages)

        # The model declined. Not an error; don't retry the same prompt.
        if resp.stop_reason == "refusal":
            return __degrade("model declined the request", messages)

        # Normal finish (end_turn / stop_sequence).
        if resp.stop_reason != "tool_use":
            draft = "".join(b.text for b in resp.content if b.type == "text")
            if reflect_rounds >= MAX_REFLECT:
                return draft

            verdict = __reflect(user_que, draft)   # ← HERE — the only call
            output_spent += verdict["usage"].output_tokens

            if verdict["ok"]:
                return draft

            # Draft failed review. Keep it, feed the critique back as a fresh
            # user turn, and let the loop continue — the model can call more
            # tools or rewrite. reflect_rounds bounds this; MAX_ITERATIONS again.
            reflect_rounds += 1
            messages.append({"role": "assistant", "content": resp.content})
            messages.append({
                "role": "user",
                "content": (
                    "A reviewer found this answer incomplete:\n"
                    f"{verdict['fix']}\n\n"
                    "Close the gap (use the tools if needed), then give the full answer."
                ),
            })
            continue


        # Budget check goes HERE: we know more work is coming, so stop
        if output_spent >= MAX_OUTPUT_TOKENS:
            messages.append({"role": "assistant", "content": resp.content})
            return __degrade(f"output budget spent ({output_spent} tokens)", messages)

        messages.append({"role": "assistant", "content": resp.content})

        results = []

        for block in resp.content:
            if block.type == "tool_use":
                result = dispatch_fn(block.name, block.input, confirm_fn=confirm_fn)
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result["content"],
                    "is_error": result["is_error"],
                })

        messages.append({"role": "user", "content": results})

    # Fell out of the for loop — the model kept asking for tools and never
    return __degrade(f"hit MAX_ITERATIONS ({MAX_ITERATIONS})", messages)


def cli_confirm(name: str, args: dict) -> bool:
    """Interactive human confirmation for a state-changing tool.

    Fail closed: only an explicit 'y'/'yes' approves. Just pressing Enter,
    or anything else, is a no. This is the human-in-the-loop for writes.
    """
    arg_str = ", ".join(f"{k}={v!r}" for k, v in args.items())
    print("\n  ⚠  The agent wants to run a state-changing tool:")
    print(f"       {name}({arg_str})")
    return input("     Approve? [y/N] ").strip().lower() in {"y", "yes"}


if __name__ == "__main__":
    import sys
    question = " ".join(sys.argv[1:]) or "What are our best-selling products?"
    print(f"Q: {question}\n")
    print(run_agent(question, confirm_fn=cli_confirm))

    