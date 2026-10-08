from penny.kb.checks import BANNED_PHRASES
from penny.principles import Principle, load_principles, voice_block


def test_four_unique_principles_load():
    principles = load_principles()
    assert [p.id for p in principles] == ["drops", "together", "learn-not-gamble", "practice"]
    assert len({p.id for p in principles}) == 4
    assert all(p.summary and p.voice for p in principles)


def test_voice_block_names_every_principle():
    block = voice_block()
    for principle in load_principles():
        assert principle.name in block
    assert block.startswith("Penny's values")


def test_voice_block_accepts_a_custom_list():
    custom = [Principle(id="x", name="Only one", summary="S.", voice="V.")]
    block = voice_block(custom)
    assert block.splitlines()[1:] == ["- Only one: S. V."]


def test_principles_never_use_the_wording_the_guardian_blocks():
    text = " ".join(f"{p.summary} {p.voice}" for p in load_principles()).lower()
    assert "rich" not in text
    assert [phrase for phrase in BANNED_PHRASES if phrase in text] == []


def test_the_family_principle_is_worded_as_security_not_riches():
    together = next(p for p in load_principles() if p.id == "together")
    assert "secure" in together.summary
    assert "rich" not in together.summary.lower()
