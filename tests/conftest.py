import pytest

import store
import tools


@pytest.fixture(autouse=True)
def fresh_state(tmp_path, monkeypatch):
    """Every test gets its own fresh copy of the seed data, in a temporary folder."""
    monkeypatch.setattr(store, "STATE_DIR", tmp_path / "state")
    store.reset()
    # Tests answer the approval prompt with a scripted "yes" unless they say otherwise.
    monkeypatch.setattr(tools, "APPROVAL_MODE", "yes")
