"""Treat every tool argument as untrusted input.

The model CHOSE the tool and filled in the values; nothing has checked
them yet. The JSON schema in tools.json only *declares* what's allowed -
it's a request to the model, not an enforcement layer. This module is
the enforcement layer, sitting between the decision and the execution.

Two kinds of bad argument, handled differently:
  REJECT - the model got it wrong and should retry (unknown status,
           a name where an integer id belongs).
  CLAMP  - the intent is fine, the number is unreasonable (limit=999999).
           Silently capping beats burning an iteration on a scolding.
"""


class ValidationError(Exception):
    """The model's arguments are unusable as-is."""


MAX_LIMIT = 100
MAX_SEARCH_LEN = 100
ORDER_STATUSES = {"pending", "shipped", "delivered", "cancelled"}


def _require(args: dict, field: str):
    if field not in args:
        raise ValidationError(f"missing required argument {field!r}")
    return args[field]


def _positive_int(value, field: str) -> int:
    # bool is a SUBCLASS of int in Python, so isinstance(True, int) is True.
    # Without this guard, True would sail through as the id 1.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"{field} must be an integer, got {value!r}")
    if value < 1:
        raise ValidationError(f"{field} must be 1 or greater, got {value}")
    return value


def _clamped_limit(value, default: int) -> int:
    """CLAMP, don't reject - an absurd limit is a fine intent, bad number."""
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"limit must be an integer, got {value!r}")
    return max(1, min(value, MAX_LIMIT))


# --- one validator per tool -------------------------------------------
# Each returns a NEW dict containing only keys the handler accepts, so a
# key the model invented is dropped instead of reaching fn(**args).

def _get_customer(args: dict) -> dict:
    return {"customer_id": _positive_int(_require(args, "customer_id"), "customer_id")}


def _list_orders(args: dict) -> dict:
    clean = {"limit": _clamped_limit(args.get("limit"), 10)}

    if args.get("customer_id") is not None:
        clean["customer_id"] = _positive_int(args["customer_id"], "customer_id")

    if args.get("status") is not None:
        status = args["status"]
        if status not in ORDER_STATUSES:
            raise ValidationError(
                f"status must be one of {sorted(ORDER_STATUSES)}, got {status!r}"
            )
        clean["status"] = status

    return clean


def _revenue_by_product(args: dict) -> dict:
    return {}   # takes no arguments; anything sent is dropped


def _search_customers(args: dict) -> dict:
    text = _require(args, "name_contains")

    if not isinstance(text, str):
        raise ValidationError(f"name_contains must be text, got {text!r}")

    text = text.strip()

    if not text:
        raise ValidationError("name_contains cannot be empty")

    # A very long pattern makes Postgres scan hard for no useful result.
    if len(text) > MAX_SEARCH_LEN:
        raise ValidationError(f"name_contains is too long (max {MAX_SEARCH_LEN} characters)")

    return {"name_contains": text, "limit": _clamped_limit(args.get("limit"), 10)}


def _list_products(args: dict) -> dict:
    flag = args.get("in_stock_only", False)

    if not isinstance(flag, bool):
        raise ValidationError(f"in_stock_only must be true or false, got {flag!r}")

    return {"in_stock_only": flag, "limit": _clamped_limit(args.get("limit"), 20)}


def _top_customers(args: dict) -> dict:
    return {"limit": _clamped_limit(args.get("limit"), 5)}


def _cancel_order(args: dict) -> dict:
    return {"order_id": _positive_int(_require(args, "order_id"), "order_id")}


VALIDATORS = {
    "get_customer": _get_customer,
    "list_orders": _list_orders,
    "revenue_by_product": _revenue_by_product,
    "search_customers": _search_customers,
    "list_products": _list_products,
    "top_customers": _top_customers,
    "cancel_order": _cancel_order
}


def validate(name: str, args: dict) -> dict:
    """Return a cleaned copy of args, or raise ValidationError."""
    validator = VALIDATORS.get(name)

    # Also your drift guard: add a tool to HANDLERS and forget it here,
    # and it fails loudly on first use instead of running unchecked.
    if validator is None:
        raise ValidationError(f"no validator registered for tool {name!r}")

    if not isinstance(args, dict):
        raise ValidationError(f"tool arguments must be an object, got {type(args).__name__}")

    return validator(args)
