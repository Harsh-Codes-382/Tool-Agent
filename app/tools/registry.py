from pathlib import Path
import json

from app.tools import handlers
from app.validation import ValidationError, validate


TOOLS_PATH = Path(__file__).parent / 'tools.json'


with TOOLS_PATH.open() as f:
    TOOLS = json.load(f)

# --- What CODE uses: tool name -> the function that runs it ------
HANDLERS = {
    "get_customer": handlers.get_customer,
    "list_orders": handlers.list_orders,
    "revenue_by_product": handlers.revenue_by_product,
    "search_customers": handlers.search_customers,
    "list_products": handlers.list_products,
    "top_customers": handlers.top_customers,
}

def dispatch(name: str, tool_input: dict) -> dict:
    """Run one tool call and ALWAYS return a string.

    Contract: this never raises. Every failure becomes a message the model
    can read on its next turn, so a bad tool call costs one iteration
    instead of killing the whole run.
    """

    fn = HANDLERS.get(name)

    if fn is None:
        available = ",".join(sorted(HANDLERS))
        return {
            "content": f"Error: unknown tool {name!r}. Available tools: {available}.",
            "is_error": True
        }

    try:
        clean_input = validate(name, tool_input)
        output = fn(**clean_input)


    except ValidationError as ve:
        return {
            "content": f"Error: invalid arguments for {name}: {ve}",
            "is_error": True
        }

    # Argument mismatch: unexpected keyword, or a required one missing.
    except TypeError as e:
        return {
            "content": f"Error: bad arguments for {name}: {e}",
            "is_error": True
        }

    # The handler itself failed — DB down, query timeout, bad value.
    except Exception as e:
        return {
            "content": f"Error running {name}: {type(e).__name__}: {e}",
            "is_error": True
        }

    return {
        "content": json.dumps(output, default=str),
        "is_error": False
    }


