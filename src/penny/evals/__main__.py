"""Run the evals against the real models, prices and article index, and write the report.

    python -m penny.evals                      # every suite, once
    python -m penny.evals routing guardian     # some suites
    python -m penny.evals --repeat 3           # repeat the model-based suites, to see the spread

Needs the keys in .env and a built index (`make kb-index`). It costs a little: one full run makes
about 120 model calls, mostly on the fast model. The report goes to docs/evals/.
"""

from __future__ import annotations

import argparse
from datetime import datetime

from penny.config import load_env
from penny.evals import cases
from penny.evals.report import write
from penny.evals.suites import SuiteResult, run_answers, run_guardian, run_retrieval, run_routing

SUITES = ("routing", "guardian", "retrieval", "answers")


def main(argv: list[str] | None = None) -> int:
    load_env()
    parser = argparse.ArgumentParser(prog="python -m penny.evals")
    parser.add_argument("suites", nargs="*", help=f"any of {', '.join(SUITES)} (default: all)")
    parser.add_argument("--repeat", type=int, default=1, help="rounds of each model-based suite")
    args = parser.parse_args(argv)
    unknown = sorted(set(args.suites) - set(SUITES))
    if unknown:
        parser.error(f"unknown suite(s): {', '.join(unknown)}")
    if args.repeat < 1:
        parser.error("--repeat must be at least 1")
    chosen = [name for name in SUITES if name in args.suites] or list(SUITES)

    # Imported late: they pull in the LLM, market and index code.
    from penny.agents.guardian import LLMGuardian
    from penny.agents.router import LLMRouter
    from penny.llm.factory import get_llm
    from penny.observability import InMemoryTraceSink
    from penny.runtime import build_penny, load_index

    setup = get_llm()
    index = load_index()
    info = {
        "provider": setup.provider,
        "fast model": setup.fast_model,
        "main model": setup.main_model,
        "embedder": index.embedder.name,
        "rounds": str(args.repeat),
    }
    results: list[SuiteResult] = []
    for name in chosen:
        print(f"running {name}...", flush=True)
        if name == "routing":
            router = LLMRouter(setup.client, setup.fast_model)
            results.append(run_routing(router, cases.routing_cases(), args.repeat))
        elif name == "guardian":
            guardian = LLMGuardian(setup.client, setup.main_model)
            results.append(run_guardian(guardian, cases.guardian_cases(), args.repeat))
        elif name == "retrieval":
            results.append(run_retrieval(index, cases.retrieval_cases()))
        else:
            sink = InMemoryTraceSink()
            graph = build_penny(setup=setup, index=index, sink=sink)
            results.append(run_answers(graph, sink, cases.answer_cases(), args.repeat))
        suite = results[-1]
        print(f"  {suite.passed}/{suite.total} passed", flush=True)

    md_path, _ = write(results, info, datetime.now())
    print(f"report: {md_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
