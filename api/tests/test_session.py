import pytest

from app.db import session as session_module


class FakeSession:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def __enter__(self) -> "FakeSession":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.closed = True

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


def test_transaction_session_commits_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeSession()
    monkeypatch.setattr(session_module, "SessionLocal", lambda: fake)

    with session_module.transaction_session() as session:
        assert session is fake

    assert fake.committed is True
    assert fake.rolled_back is False
    assert fake.closed is True


def test_transaction_session_rolls_back_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeSession()
    monkeypatch.setattr(session_module, "SessionLocal", lambda: fake)

    with pytest.raises(RuntimeError):
        with session_module.transaction_session():
            raise RuntimeError("boom")

    assert fake.committed is False
    assert fake.rolled_back is True
    assert fake.closed is True
