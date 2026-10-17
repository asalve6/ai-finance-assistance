from penny.agents.prompts import system_prompt
from penny.graph.types import AgentRequest, KidContext


def request(**fields) -> AgentRequest:
    return AgentRequest(trace_id="t", kid=KidContext(nickname="Sam"), question="q", **fields)


def test_a_plain_request_has_no_extra_parts():
    prompt = system_prompt(request(), "ROLE", "RULES")
    assert "a child called Sam. ROLE" in prompt and "RULES" in prompt
    assert "different helper" not in prompt and "not accepted" not in prompt


def test_the_other_part_of_a_mixed_question_is_left_to_its_helper():
    prompt = system_prompt(request(also_ask="How do I save for a bike?"), "ROLE", "RULES")
    assert '"How do I save for a bike?". Answer only the rest' in prompt
