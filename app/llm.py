import os
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

# Anthropic() automatically reads ANTHROPIC_API_KEY from the environment
# (which load_dotenv just populated from your .env file).
# timeout + max_retries are the note-06 reliability basics. The SDK already
# retries 429 (rate limit) / 5xx / connection errors with exponential backoff.
client = Anthropic(timeout=30.0, max_retries=2)

# One-line lever to trade cost vs capability (your note 05):
#   claude-opus-4-8   → most capable (default)
#   claude-sonnet-5   → cheaper, still strong at tool-calling
#   claude-haiku-4-5  → cheapest/fastest, fine for simple routing
MODEL = "claude-opus-4-8"

def call_model(messages, tools=None, system=None):
    """One call to Claude. Returns the raw response object."""
    kwargs = {
        "model": MODEL,
        "max_tokens": 4096,
        "messages": messages,
        "cache_control": {"type": "ephemeral"}
    }
    if tools:
        kwargs["tools"] = tools
    if system:
        kwargs["system"] = system
    return client.messages.create(**kwargs)

