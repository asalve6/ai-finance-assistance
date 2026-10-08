"""Define a tool from a pydantic model, so its inputs are validated before the function runs."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from penny.contracts import ToolSpec


def make_tool(
    name: str, description: str, args: type[BaseModel], fn: Callable[..., Any]
) -> ToolSpec:
    """`args` describes the inputs. The model sees its JSON schema. When the tool is called, the
    arguments are checked against it first, so `fn` only ever receives valid, typed values. A bad
    call raises, and the agent loop reports that back to the model.

    The description should say what the tool does, when to call it, and when not to.
    """

    def validated(**raw: Any) -> Any:
        return fn(**args(**raw).model_dump())

    return ToolSpec(
        name=name, description=description, input_schema=args.model_json_schema(), fn=validated
    )
