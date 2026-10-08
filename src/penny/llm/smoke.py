"""A live end-to-end check of the configured provider: `python -m penny.llm.smoke`.

Asks a question that needs a tool, runs the tool, sends the result back and prints the final
answer. It proves the tool-call round trip works with the real API. It costs a fraction of a cent.
"""

from __future__ import annotations

import argparse
import json
import sys

from penny.config import load_env
from penny.contracts import LLMClient, Message, ToolSpec
from penny.llm.errors import LLMError
from penny.llm.factory import get_llm

ADD_TOOL = ToolSpec(
    name="add",
    description="Add two whole numbers. Use it for any addition instead of working it out.",
    input_schema={
        "type": "object",
        "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
        "required": ["a", "b"],
    },
    fn=lambda a, b: a + b,
)


def run_smoke(client: LLMClient, model: str) -> dict:
    """Two model calls: one that should ask for the tool, one that should use its result."""
    system = "You are a careful assistant. Use tools when they apply and keep answers short."
    messages = [Message.user("What is 17 plus 25? Use the add tool.")]
    first = client.complete(model=model, system=system, messages=messages, tools=[ADD_TOOL])
    if first.stop_reason != "tool_use" or not first.tool_calls:
        return {"ok": False, "step": "tool request", "detail": first.text or first.stop_reason}
    call = first.tool_calls[0]
    if call.error:
        return {"ok": False, "step": "tool arguments", "detail": call.error}

    result = ADD_TOOL.fn(**call.input)
    messages += [first.to_message(), Message.tool_result(call.id, json.dumps({"sum": result}))]
    final = client.complete(model=model, system=system, messages=messages, tools=[ADD_TOOL])
    return {
        "ok": "42" in final.text and result == 42,
        "step": "final answer",
        "detail": final.text.strip(),
        "tool_input": call.input,
        "tokens": first.input_tokens
        + first.output_tokens
        + final.input_tokens
        + final.output_tokens,
    }


def main(argv: list[str] | None = None) -> int:
    load_env()
    parser = argparse.ArgumentParser(prog="python -m penny.llm.smoke")
    parser.add_argument("--provider", default=None, help="anthropic or openai (default: .env)")
    parser.add_argument("--tier", choices=["fast", "main"], default="fast")
    args = parser.parse_args(argv)
    try:
        setup = get_llm(args.provider)
        model = setup.fast_model if args.tier == "fast" else setup.main_model
        print(f"Provider: {setup.provider}, model: {model}")
        outcome = run_smoke(setup.client, model)
    except LLMError as exc:
        print(f"Error: {exc}")
        return 2
    print(f"Tool arguments the model chose: {outcome.get('tool_input')}")
    print(f"Answer: {outcome['detail']}")
    print(f"Tokens used: {outcome.get('tokens')}")
    print("PASS" if outcome["ok"] else f"FAIL at {outcome['step']}")
    return 0 if outcome["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
