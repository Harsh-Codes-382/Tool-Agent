import json
import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from app.llm import call_model
from app.agent import run_agent
from app.tools.registry import TOOLS, dispatch
import concurrent.futures

MCP_URL = "http://127.0.0.1:8000/mcp"


STORE_SYSTEM = "You answer questions about our store using the store tools. Only state facts the tool results support."
WEB_SYSTEM   = ("You fetch web pages with the web tools and answer strictly from them. "
      "Fetch the EXACT URL the user gives you — never substitute mirrors, mobile "
      "versions, REST APIs, caches, proxies, or alternate sources. Normally ONE "
      "fetch is enough: if the page returns successfully, answer from it even if "
      "the text is truncated — a partial page is fine for a summary. Only fetch "
      "again if the previous call returned an error. Always cite the URL you used.")


SUPERVISOR_SYSTEM = (
    "You are a supervisor. You do NOT answer directly and you have no data "
    "of your own. Delegate to specialists: ask_store_agent for anything about "
    "our store's customers/orders/products (the database); ask_web_agent for "
    "live or external info from the public web. You may call more than one, "
    "or the same one several times. When you have enough, synthesize a single "
    "final answer for the user."
)

 # Each specialist is advertised as ONE tool that takes a natural-language task.
SUPERVISOR_TOOLS = [
    {
        "name": "ask_store_agent",
        "description": "Ask the store specialist a question about customers, orders, or products in our database.",
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "A self-contained question for the store specialist."}
            },
            "required": ["question"],
        },
    },
    {
        "name": "ask_web_agent",
        "description": "Ask the web specialist to look something up on the public web (needs a URL or a fetchable page).",
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "A self-contained task for the web specialist."}
            },
            "required": ["question"],
        },
    },
]


async def on_progress(progress: float, total: float | None, message: str | None) -> None:
    pct = f"{progress:.0f}/{total:.0f}" if total else f"{progress:.0f}"
    print(f"  [progress {pct}] {message or ''}")


def store_agent(question: str) -> str:
    # No overrides -> uses the store defaults (TOOLS, dispatch).
    return run_agent(question, system=STORE_SYSTEM)

def web_agent(question: str) -> str:
    return run_agent(question, tools=web_tool_schema(), system=WEB_SYSTEM, dispatch_fn=web_dispatch)

def _run_async(coro):
    """Drive an async coroutine to completion from sync code, whether or
    not an event loop is already running in the current thread."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No loop here (e.g. the CLI). Simplest path.
        return asyncio.run(coro)

    # A loop IS running (e.g. we're inside the async /ask route). We can't
    # reuse it for a blocking call, so hand the coroutine to a worker
    # thread that spins up its OWN loop, and wait for the answer.
    #   Trade-off: .result() blocks the calling thread until MCP returns.
    #   That's fine as long as /ask offloads run_supervisor to a threadpool
    #   (so the caller is a worker, not the event-loop thread itself).
    with concurrent.futures.ThreadPoolExecutor(1) as pool:
        return pool.submit(asyncio.run, coro).result()

async def _list_tools():
    async with streamable_http_client(MCP_URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return (await session.list_tools()).tools

async def _call_tool(name: str, args: dict):
    async with streamable_http_client(MCP_URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return (await session.call_tool(
                arguments=args, 
                name=name,
                progress_callback=on_progress
                ))


def web_tool_schema() -> list:
    tools = _run_async(_list_tools())
    return [
        {
            "name" : t.name,
            "description": t.description,
            "input_schema": t.input_schema,
        }
        for t in tools
    ]


def web_dispatch(name: str, tool_input: dict) -> dict:
    """Relay one MCP tool call. Same {content, is_error} contract as
    registry.dispatch — so agent_loop can't tell the two apart."""
    try:
        result = _run_async(_call_tool(name, tool_input))
    except Exception as e:
        return {"content": f"Error calling {name!r} over MCP: {e}", "is_error": True}

    if getattr(result, "isError", False):
        text = "".join(getattr(b, "text", "") for b in result.content)
        return {"content": text or f"{name} reported an error.", "is_error": True}

    if result.structured_content is not None:
        return {"content": json.dumps(result.structured_content), "is_error": False}

    text = "".join(getattr(b, "text", "") for b in result.content)
    return {"content": text, "is_error": False}



def supervisor_dispatch(name: str, tool_input: dict) -> dict:
    """Route a supervisor 'tool call' to a real specialist. The specialist
    runs a whole agent loop; its final string is the tool result. Same
    {content, is_error} contract as every other dispatch."""
    question = tool_input.get("question", "")
    try:
        if name == "ask_store_agent":
            return {"content": store_agent(question), "is_error": False}
        if name == "ask_web_agent":
            return {"content": web_agent(question), "is_error": False}
        return {"content": f"Error: unknown specialist {name!r}.", "is_error": True}
    except Exception as e:
        # A specialist blowing up is one bad tool result, not a dead run.
        return {"content": f"Error: {name} failed: {e}", "is_error": True}



def run_supervisor(question: str) -> str:
    return run_agent(
        question,
        tools=SUPERVISOR_TOOLS,
        system=SUPERVISOR_SYSTEM,
        dispatch_fn=supervisor_dispatch,
    )

if __name__ == "__main__":
    import sys
    question = " ".join(sys.argv[1:]) or "Who are our top customers?"
    print(f"Q: {question}\n")
    print(run_supervisor(question))


