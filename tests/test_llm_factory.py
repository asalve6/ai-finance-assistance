import pytest

from penny.llm.anthropic_client import AnthropicClient
from penny.llm.errors import LLMError
from penny.llm.factory import DEFAULT_MODELS, get_llm
from penny.llm.openai_client import OpenAIClient


def test_anthropic_is_the_default_provider_with_default_models():
    setup = get_llm(env={})
    assert isinstance(setup.client, AnthropicClient)
    assert (setup.provider, setup.fast_model, setup.main_model) == (
        "anthropic",
        "claude-haiku-5-5",
        "claude-sonnet-5-5",
    )


def test_openai_gets_its_own_default_models():
    setup = get_llm(env={"LLM_PROVIDER": "openai"})
    assert isinstance(setup.client, OpenAIClient)
    assert (setup.fast_model, setup.main_model) == ("gpt-4o-mini", "gpt-4o")


def test_models_from_the_environment_override_the_defaults():
    env = {"LLM_PROVIDER": "openai", "LLM_MODEL_FAST": "gpt-4o", "LLM_MODEL_MAIN": "gpt-5"}
    setup = get_llm(env=env)
    assert (setup.fast_model, setup.main_model) == ("gpt-4o", "gpt-5")


def test_blank_model_settings_count_as_unset():
    env = {"LLM_PROVIDER": "openai", "LLM_MODEL_FAST": "  ", "LLM_MODEL_MAIN": ""}
    setup = get_llm(env=env)
    assert (setup.fast_model, setup.main_model) == ("gpt-4o-mini", "gpt-4o")


def test_the_provider_argument_beats_the_environment_and_is_case_insensitive():
    setup = get_llm(" OpenAI ", env={"LLM_PROVIDER": "anthropic"})
    assert setup.provider == "openai"


def test_switching_provider_but_keeping_the_old_model_names_is_caught_early():
    env = {"LLM_PROVIDER": "openai", "LLM_MODEL_MAIN": "claude-sonnet-5-5"}
    with pytest.raises(LLMError, match=r"LLM_MODEL_MAIN='claude-sonnet-5-5'.*gpt-4o") as raised:
        get_llm(env=env)
    assert "Anthropic" in str(raised.value)


def test_an_openai_model_under_the_anthropic_provider_is_caught_too():
    env = {"LLM_PROVIDER": "anthropic", "LLM_MODEL_FAST": "gpt-4o-mini"}
    with pytest.raises(LLMError, match=r"LLM_MODEL_FAST='gpt-4o-mini'.*claude-haiku-5-5"):
        get_llm(env=env)


def test_an_unknown_provider_is_refused():
    with pytest.raises(LLMError, match="Unknown LLM_PROVIDER 'gemini'"):
        get_llm(env={"LLM_PROVIDER": "gemini"})


def test_it_reads_the_real_environment_by_default(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("LLM_MODEL_FAST", raising=False)
    monkeypatch.delenv("LLM_MODEL_MAIN", raising=False)
    assert get_llm().provider == "openai"


def test_default_models_exist_for_every_provider_and_tier():
    for models in DEFAULT_MODELS.values():
        assert set(models) == {"fast", "main"}
