from pydantic import BaseModel


def single_tool_choice(response_model: type[BaseModel]) -> dict:
    """
    `tool_choice` for every instructor structured call: force the response
    model's own tool and forbid parallel tool calls.

    Why (full-pass failure, Session 26): judgment responses sometimes came
    back as several parallel `tool_use` blocks of the same tool. That fails
    validation, and instructor's re-ask then sends those tool calls back
    without the `tool_result` blocks the API requires, so the API rejects it
    (400) and the whole (doc, run) is lost. With parallel tool use disabled
    the model must answer with exactly one tool call.

    instructor keeps a caller-supplied `tool_choice` unchanged
    (v2/providers/anthropic/handlers.py), and names the tool after the
    response model's class, which this matches.
    """
    return {"type": "tool", "name": response_model.__name__, "disable_parallel_tool_use": True}
