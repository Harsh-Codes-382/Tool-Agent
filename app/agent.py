import json
from app.llm import call_model
from app.tools.registry import dispatch, TOOLS

MAX_ITERATIONS = 10        # model calls per question
MAX_OUTPUT_TOKENS = 20_000 # cumulative output budget across the whole run

SYSTEM = "You answer questions about our store using the provided tools. Only state facts the tool results support."

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

def run_agent(user_que: str, *, tools=None, system=None, dispatch_fn = None) -> str:
    messages = [{'role': "user", "content": user_que}]
    output_spent = 0

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
            return "".join(b.text for b in resp.content if b.type == "text")


        # Budget check goes HERE: we know more work is coming, so stop
        if output_spent >= MAX_OUTPUT_TOKENS:
            messages.append({"role": "assistant", "content": resp.content})
            return __degrade(f"output budget spent ({output_spent} tokens)", messages)

        messages.append({"role": "assistant", "content": resp.content})

        results = []

        for block in resp.content:
            if block.type == "tool_use":
                result = dispatch_fn(block.name, block.input)
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result["content"],
                    "is_error": result["is_error"],
                })

        messages.append({"role": "user", "content": results})

    # Fell out of the for loop — the model kept asking for tools and never
    return __degrade(f"hit MAX_ITERATIONS ({MAX_ITERATIONS})", messages)


if __name__ == "__main__":
    import sys
    question = " ".join(sys.argv[1:]) or "What are our best-selling products?"
    print(f"Q: {question}\n")
    print(run_agent(question))

    