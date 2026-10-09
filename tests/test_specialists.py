from kb_helpers import corpus
from penny.agents.specialists import TAX_NOTE, TAX_ROLE, build_finance_qa, build_tax
from penny.contracts import Level, LLMResponse
from penny.graph.types import AgentRequest, KidContext
from penny.kb.embedding import HashingEmbedder
from penny.kb.index import KBIndex
from penny.llm.factory import LLMSetup
from penny.llm.fake import FakeLLM
from penny.observability import InMemoryTraceSink

INDEX = KBIndex.build(corpus(draft_bond=False), HashingEmbedder())


def setup(*texts: str) -> LLMSetup:
    return LLMSetup(FakeLLM([LLMResponse(text=t) for t in texts]), "fake", "fast-m", "main-m")


def request(question: str) -> AgentRequest:
    return AgentRequest(trace_id="t", kid=KidContext(level=Level.STARTER), question=question)


def test_the_tax_agent_answers_from_the_tax_article_and_always_adds_the_disclaimer():
    llm_setup = setup("Some of your pay goes to the government as tax.")
    reply = build_tax(llm_setup, INDEX).respond(request("why is tax taken from my paycheck"))
    assert reply.text == f"Some of your pay goes to the government as tax. {TAX_NOTE}"
    assert reply.citations[0].article_id == "what-are-taxes"


def test_the_tax_agent_has_its_own_role_name_and_model():
    sink = InMemoryTraceSink()
    llm_setup = setup("ok")
    build_tax(llm_setup, INDEX, sink).respond(request("why is tax taken from my paycheck"))
    call = llm_setup.client.calls[0]
    assert TAX_ROLE in call["system"] and call["model"] == "main-m"
    assert "tax professional" in call["system"] and "never state a tax rate" in call["system"]
    assert {e.agent for e in sink.events} == {"tax"}


def test_finance_qa_has_no_disclaimer_and_its_own_name():
    sink = InMemoryTraceSink()
    llm_setup = setup("A stock is a small piece of a company.")
    reply = build_finance_qa(llm_setup, INDEX, sink).respond(request("what is a stock"))
    assert reply.text == "A stock is a small piece of a company."
    assert TAX_ROLE not in llm_setup.client.calls[0]["system"]
    assert {e.agent for e in sink.events} == {"finance_qa"}


def test_the_two_agents_are_separate_objects_with_different_prompts():
    llm_setup = setup("a", "b")
    tax, qa = build_tax(llm_setup, INDEX), build_finance_qa(llm_setup, INDEX)
    assert tax is not qa and tax.name != qa.name and tax.role != qa.role
    assert (tax.closing_note, qa.closing_note) == (TAX_NOTE, None)
