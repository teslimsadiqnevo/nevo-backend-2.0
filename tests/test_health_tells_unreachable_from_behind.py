"""A database nobody can reach must not read as a migration to run.

On 6 November the backend was down for about sixteen hours. /health answered
200 the whole time, with schema "unknown" and the applied revision blank,
which is what it also says when the migration table is empty. The console
read it as a schema problem and asked whether the migration had been
applied; it had. Every database read was failing at pool_timeout.

Two different facts had collapsed into one answer. They are now separate.
"""

from __future__ import annotations

import asyncio

from nevo.ops.schema_version import schema_state


class _Unreachable:
    """An engine whose connect() fails, as it does when the pooler is full."""

    def connect(self):
        raise OSError("connection refused")


class _Empty:
    """An engine that answers and has no revision in it."""

    def connect(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def execute(self, _statement: object):
        class Result:
            @staticmethod
            def scalar() -> None:
                return None

        return Result()


def test_an_unreachable_database_says_so() -> None:
    state = asyncio.run(schema_state(_Unreachable()))
    assert state["state"] == "unreachable"
    # The class name, so the log and the health body agree on what failed,
    # and not the message, which can carry the connection string.
    assert state["error"] == "OSError"


def test_a_reachable_database_with_no_revision_is_still_unknown() -> None:
    # The case the old answer was right about, and which must not now be
    # reported as a connection failure.
    state = asyncio.run(schema_state(_Empty()))
    assert state["state"] == "unknown"
    assert state["error"] is None


def test_health_carries_the_reason() -> None:
    import inspect

    from nevo import main

    source = inspect.getsource(main)
    assert '"schemaError"' in source


def test_the_expected_revision_is_still_reported_when_unreachable() -> None:
    # It comes from the migration files, not the database, so it is the one
    # thing still knowable - and it is what tells you which revision the
    # running code wants once the connection is back.
    state = asyncio.run(schema_state(_Unreachable()))
    assert state["expected"] is not None
