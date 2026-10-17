import json
from datetime import datetime

import pytest

from kb_helpers import corpus
from penny.contracts import Level, LLMResponse, Verdict
from penny.evals import __main__ as cli
from penny.evals import cases
from penny.evals.cases import AnswerCase, GuardianCase, RetrievalCase, RoutingCase
from penny.evals.report import markdown, to_json, write
from penny.evals.suites import (
    CaseResult,
    SuiteResult,
    check_answer,
    rate,
    run_answers,
    run_guardian,
    run_retrieval,
    run_routing,
)
from penny.graph.build import PennyGraph
from penny.graph.types import SPECIALISTS, RouteDecision, TurnResult
from penny.kb.embedding import HashingEmbedder
from penny.kb.index import KBIndex
from penny.llm.factory import LLMSetup
from penny.llm.fake import FakeLLM
from penny.observability import InMemoryTraceSink

INDEX = KBIndex.build(corpus(draft_bond=True), HashingEmbedder())  # the bond draft is left out
WHEN = datetime(2026, 10, 17, 9, 30)


# ------------------------------------------------------------------ the case files


def test_every_case_file_loads_with_unique_ids():
    assert len(cases.routing_cases()) >= 20
    assert len(cases.guardian_cases()) >= 12
    assert len(cases.retrieval_cases()) >= 10
    assert len(cases.answer_cases()) >= 15


def test_the_cases_cover_every_specialist_and_both_kinds_of_draft():
    assert {c.agent for c in cases.routing_cases()} == set(SPECIALISTS)
    assert {c.route for c in cases.answer_cases()} >= set(SPECIALISTS)
    assert any(c.mixed for c in cases.routing_cases())
    assert {c.bad for c in cases.guardian_cases()} == {True, False}
    assert any(c.article is None for c in cases.retrieval_cases())  # off-topic questions


def test_repeated_ids_and_unknown_agents_are_refused(tmp_path):
    (tmp_path / "routing.yaml").write_text(
        "- {id: a, question: q, agent: tax}\n- {id: a, question: q, agent: tax}\n"
    )
    with pytest.raises(ValueError, match="repeated case ids"):
        cases.routing_cases(tmp_path)
    with pytest.raises(ValueError, match="unknown agent 'astrologer'"):
        RoutingCase(id="x", question="q", agent="astrologer")
    with pytest.raises(ValueError, match="unknown agent"):
        AnswerCase(id="x", question="q", route="astrologer")


# ------------------------------------------------------------------ routing


class Answers:
    """A router that answers from a table keyed by question."""

    def __init__(self, table):
        self.table = table
        self.histories = []

    def route(self, question, history, kid, trace_id=""):
        self.histories.append(history)
        agent, also = self.table[question]
        return RouteDecision(agent=agent, reason="r", also_ask=also)


def test_routing_scores_the_agent_and_the_split():
    suite_cases = [
        RoutingCase(id="right", question="q1", agent="tax"),
        RoutingCase(id="wrong", question="q2", agent="coach"),
        RoutingCase(id="split", question="q3", agent="market", mixed=True),
        RoutingCase(id="missed-split", question="q4", agent="market", mixed=True),
        RoutingCase(id="false-split", question="q5", agent="tax", history=["hi", "hello"]),
    ]
    router = Answers(
        {
            "q1": ("tax", ""),
            "q2": ("tax", ""),
            "q3": ("market", "What is tax?"),
            "q4": ("market", ""),
            "q5": ("tax", "Something else?"),
        }
    )
    suite = run_routing(router, suite_cases)
    assert [r.passed for r in suite.results] == [True, False, True, False, False]
    assert suite.results[1].detail == "got tax (expected coach)"
    assert suite.results[3].detail.endswith("(expected a split)")
    assert suite.results[4].detail.endswith("(unexpected split)")
    assert suite.metrics["right specialist"] == "4/5 (80%)"
    assert suite.metrics["mixed questions split"] == "1/2 (50%)"
    assert suite.metrics["false splits"] == 1
    assert "median latency" in suite.metrics and "p95 latency" in suite.metrics
    history = router.histories[4]
    assert [(m.role, m.content) for m in history] == [("user", "hi"), ("assistant", "hello")]


def test_repeat_runs_every_case_again_with_numbered_ids():
    suite = run_routing(
        Answers({"q": ("tax", "")}), [RoutingCase(id="a", question="q", agent="tax")], repeat=3
    )
    assert [r.id for r in suite.results] == ["a", "a#2", "a#3"]
    assert (suite.passed, suite.total) == (3, 3)


# ------------------------------------------------------------------ guardian


class Judge:
    def __init__(self, approve_drafts):
        self.approve = approve_drafts

    def review(self, request, reply):
        if reply.text == "boom":
            raise RuntimeError("model down")
        return Verdict(
            approved=reply.text in self.approve,
            reasons=[] if reply.text in self.approve else ["no"],
        )


def test_guardian_counts_caught_bad_drafts_and_approved_good_ones():
    suite_cases = [
        GuardianCase(id="bad-caught", bad=True, question="q", draft="bad1"),
        GuardianCase(id="bad-missed", bad=True, question="q", draft="bad2"),
        GuardianCase(id="good-ok", bad=False, question="q", draft="good1"),
        GuardianCase(id="good-rejected", bad=False, question="q", draft="good2"),
        GuardianCase(id="failed-review", bad=True, question="q", draft="boom"),
    ]
    suite = run_guardian(Judge({"bad2", "good1"}), suite_cases)
    assert [r.passed for r in suite.results] == [True, False, True, False, True]
    assert suite.results[0].detail == "bad draft, rejected: no"
    assert suite.results[1].detail == "bad draft, approved"
    assert suite.results[4].detail == "bad draft, rejected: review failed: model down"
    assert suite.metrics["bad drafts caught"] == "2/3 (67%)"
    assert suite.metrics["good drafts approved"] == "1/2 (50%)"


def test_the_guardian_case_reader_level_reaches_the_reviewer():
    seen = []

    class Recorder:
        def review(self, request, reply):
            seen.append((request.kid.level, reply.evidence))
            return Verdict(approved=True)

    case = GuardianCase(
        id="g", bad=False, question="q", draft="d", evidence="e", level=Level.BUILDER
    )
    run_guardian(Recorder(), [case])
    assert seen == [(Level.BUILDER, "e")]


# ------------------------------------------------------------------ retrieval


def test_retrieval_checks_the_first_article_and_skips_articles_not_in_the_index():
    suite = run_retrieval(
        INDEX,
        [
            RetrievalCase(
                id="stock",
                question="what is a stock and who owns shares",
                article="what-is-a-stock",
            ),
            RetrievalCase(
                id="taxes", question="taxes paycheck sales tax", article="what-are-taxes"
            ),
            RetrievalCase(
                id="wrong-first",
                question="what is a stock and who owns shares",
                article="piggy-bank-basics",
            ),
            RetrievalCase(id="bond-draft", question="what is a bond", article="what-is-a-bond"),
            RetrievalCase(id="off-topic", question="zebra volcano trombone", article=None),
            RetrievalCase(id="off-topic-matched", question="piggy bank saving money", article=None),
        ],
    )
    results = {r.id: r for r in suite.results}
    assert results["stock"].passed and results["stock"].detail.startswith("top: what-is-a-stock")
    assert results["taxes"].passed
    assert results["wrong-first"].passed is False
    assert results["bond-draft"].passed is None  # a draft, so not in this index
    assert results["off-topic"].passed and results["off-topic"].detail == "nothing matched"
    assert results["off-topic-matched"].passed is False
    assert results["off-topic-matched"].detail.startswith("matched piggy-bank-basics")
    assert suite.skipped == 1 and suite.total == 5
    assert suite.metrics["articles in the index"] == 3
    assert suite.metrics["right article first"] == "2/3 (67%)"
    assert suite.metrics["off-topic left unmatched"] == "1/2 (50%)"


def test_a_question_with_no_match_says_so():
    suite = run_retrieval(
        INDEX, [RetrievalCase(id="x", question="zebra", article="what-is-a-stock")]
    )
    assert (suite.results[0].passed, suite.results[0].detail) == (False, "nothing matched")


# ------------------------------------------------------------------ answers


def turn(**fields) -> TurnResult:
    base = {
        "reply": "Save $7.50 each week.",
        "route": "coach",
        "route_reason": "r",
        "approved": True,
        "rewrites": 0,
        "fallback_used": False,
        "trace_id": "t",
    }
    return TurnResult(**{**base, **fields})


def test_check_answer_lists_every_problem():
    case = AnswerCase(
        id="c",
        question="q",
        route="coach",
        contains=["$7.50", "weeks"],
        not_contains=["SAVE"],
        also_ask=True,
    )
    assert check_answer(case, turn(route="tax", approved=False)) == [
        "routed to tax, expected coach",
        "used the safe fallback",
        'missing "weeks"',
        'should not say "SAVE"',
        "no second part offered",
    ]
    loose = AnswerCase(id="c", question="q", approved=False, also_ask=False)
    assert check_answer(loose, turn(also_ask="x")) == ["was approved", "offered a second part"]
    assert check_answer(AnswerCase(id="c", question="q"), turn()) == []


def test_answers_run_through_the_graph_with_sessions_levels_and_holdings():
    seen = []

    class Recorder:
        def respond(self, request):
            seen.append(
                (
                    request.question,
                    request.kid.level,
                    request.kid.practice_holdings,
                    len(request.history),
                )
            )
            from penny.graph.types import AgentReply

            return AgentReply(text=f"answer to {request.question}")

    sink = InMemoryTraceSink()
    graph = PennyGraph(agents={"finance_qa": Recorder()}, sink=sink)
    suite_cases = [
        AnswerCase(
            id="ok",
            question="what is a stock",
            level=Level.BUILDER,
            route="finance_qa",
            contains=["stock"],
        ),
        AnswerCase(
            id="follow-up", question="and bonds?", before=["what is a stock"], holdings={"DIS": 1}
        ),
        AnswerCase(id="bad", question="hi", contains=["nope"]),
    ]
    suite = run_answers(graph, sink, suite_cases)
    assert [r.passed for r in suite.results] == [True, True, False]
    assert suite.results[0].detail.startswith("finance_qa, 0 rewrites | answer to what is a stock")
    assert suite.results[2].detail.startswith('missing "nope"')
    assert seen[0] == ("what is a stock", Level.BUILDER, {}, 0)
    assert seen[2] == ("and bonds?", Level.STARTER, {"DIS": 1}, 2)  # asked after the earlier turn
    assert suite.metrics["right specialist"] == "3/3 (100%)"
    assert suite.metrics["approved by the Guardian"] == "3/3 (100%)"
    assert suite.metrics["safe fallback used"] == "0/3 (0%)"
    assert suite.metrics["rewrites per answer"] == "0.00"
    assert suite.metrics["tokens per answer"] == "0"


def test_a_crashing_graph_fails_the_case_but_not_the_run():
    class Crashing:
        def ask(self, question, *, session_id, kid):
            raise RuntimeError("boom")

    suite = run_answers(Crashing(), InMemoryTraceSink(), [AnswerCase(id="c", question="q")])
    assert suite.results[0].passed is False and suite.results[0].detail == "crashed: boom"
    assert suite.metrics["tokens per answer"] == "0"


def test_empty_suites_report_not_applicable():
    assert rate(0, 0) == "n/a"
    suite = run_answers(PennyGraph(), InMemoryTraceSink(), [])
    assert suite.metrics["rewrites per answer"] == "n/a" and "median latency" not in suite.metrics


# ------------------------------------------------------------------ report


def sample_suites():
    return [
        SuiteResult(
            name="routing",
            results=[
                CaseResult(id="a", passed=True, detail="got tax", latency_ms=12),
                CaseResult(id="b", passed=False, detail="got | pipes\nand lines"),
                CaseResult(id="c", passed=None, detail="skipped"),
            ],
            metrics={"right specialist": "1/2 (50%)"},
        )
    ]


def test_the_markdown_report_has_a_summary_and_every_case():
    text = markdown(sample_suites(), {"provider": "openai"}, WHEN)
    assert text.startswith("# Penny eval report\n\nRun on 2026-10-17 09:30. provider: openai.")
    assert "| routing | 1/2 (50%) (1 skipped) | right specialist: 1/2 (50%) |" in text
    assert "| a | pass | got tax | 12 |" in text
    assert "| b | **FAIL** | got \\| pipes and lines |  |" in text
    assert "| c | skip | skipped |  |" in text


def test_the_json_report_keeps_every_number(tmp_path):
    data = json.loads(to_json(sample_suites(), {"provider": "openai"}, WHEN))
    assert data["run_at"] == "2026-10-17T09:30:00"
    suite = data["suites"][0]
    assert (suite["passed"], suite["total"], suite["skipped"]) == (1, 2, 1)
    assert suite["results"][1]["detail"] == "got | pipes\nand lines"
    md_path, json_path = write(sample_suites(), {}, WHEN, tmp_path / "out")
    assert md_path.read_text().startswith("# Penny eval report")
    assert json.loads(json_path.read_text())["suites"][0]["name"] == "routing"


# ------------------------------------------------------------------ the command


def test_unknown_suites_and_bad_repeats_are_refused(capsys):
    with pytest.raises(SystemExit):
        cli.main(["astrology"])
    assert "unknown suite(s): astrology" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        cli.main(["--repeat", "0"])


def test_the_command_runs_the_chosen_suites_and_writes_the_report(monkeypatch, tmp_path, capsys):
    import penny.llm.factory
    import penny.runtime

    verdicts = [
        LLMResponse(
            text=json.dumps({"approved": not c.bad, "problems": [] if not c.bad else ["x"]})
        )
        for c in cases.guardian_cases()
    ]
    setup = LLMSetup(FakeLLM(verdicts), "fake", "fast-m", "main-m")
    monkeypatch.setattr(penny.llm.factory, "get_llm", lambda: setup)
    monkeypatch.setattr(penny.runtime, "load_index", lambda: INDEX)
    monkeypatch.setattr(
        penny.runtime, "build_penny", lambda setup, index, sink: PennyGraph(sink=sink)
    )
    written = {}

    def write_here(suites, info, when):
        written["info"] = info
        return write(suites, info, when, tmp_path)

    monkeypatch.setattr(cli, "write", write_here)
    assert cli.main(["answers", "guardian", "retrieval"]) == 0
    out = capsys.readouterr().out
    # suites run in the fixed order, whatever order they were asked in
    assert (
        out.index("running guardian")
        < out.index("running retrieval")
        < out.index("running answers")
    )
    assert f"{len(verdicts)}/{len(verdicts)} passed" in out
    assert (
        written["info"]["fast model"] == "fast-m" and written["info"]["embedder"] == "hashing-512"
    )
    report = (tmp_path / "report.md").read_text()
    assert "## Guardian" in report and "## Retrieval" in report and "## Answers" in report
    assert "## Routing" not in report
