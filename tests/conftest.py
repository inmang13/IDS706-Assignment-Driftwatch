import pytest


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    """Tests never call an LLM, whatever .env or the shell says."""
    monkeypatch.setenv("LLM", "fallback")


@pytest.fixture(autouse=True, scope="session")
def _no_context_files(tmp_path_factory):
    """Agent runs in tests never see the committed data/context/*.json web leads; a test that
    wants a lead points context.CONTEXT_DIR at its own fixture file."""
    from driftwatch.agents import context

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(context, "CONTEXT_DIR", tmp_path_factory.mktemp("no_context"))
        yield
