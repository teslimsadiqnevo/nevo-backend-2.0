import os
import uuid

import asyncpg
import pytest

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not TEST_DATABASE_URL,
        reason="TEST_DATABASE_URL is required for PostgreSQL integration tests",
    ),
]


def asyncpg_url() -> str:
    assert TEST_DATABASE_URL is not None
    return TEST_DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)


async def create_learner(connection: asyncpg.Connection) -> uuid.UUID:
    # learner_id references users.id since SCRUM-16 closed the deferred FK.
    learner_id = await connection.fetchval(
        "INSERT INTO users (role, auth_method) VALUES ('student', 'pin') RETURNING id"
    )
    assert isinstance(learner_id, uuid.UUID)
    return learner_id


async def test_profile_constraints_and_unique_learner() -> None:
    connection = await asyncpg.connect(asyncpg_url())
    try:
        learner_id = await create_learner(connection)
        profile_id = await connection.fetchval(
            """
            INSERT INTO learner_profiles (learner_id, cognitive_load_threshold)
            VALUES ($1, 3)
            RETURNING id
            """,
            learner_id,
        )
        assert profile_id is not None

        with pytest.raises(asyncpg.UniqueViolationError):
            await connection.execute(
                "INSERT INTO learner_profiles (learner_id) VALUES ($1)",
                learner_id,
            )
    finally:
        await connection.close()


async def test_profile_rejects_out_of_range_observations() -> None:
    connection = await asyncpg.connect(asyncpg_url())
    try:
        learner_id = await create_learner(connection)
        with pytest.raises(asyncpg.CheckViolationError):
            await connection.execute(
                """
                INSERT INTO learner_profiles (
                    learner_id,
                    cognitive_load_threshold
                )
                VALUES ($1, 6)
                """,
                learner_id,
            )
    finally:
        await connection.close()


async def test_history_rows_are_immutable() -> None:
    connection = await asyncpg.connect(asyncpg_url())
    try:
        learner_id = await create_learner(connection)
        profile_id = await connection.fetchval(
            """
            INSERT INTO learner_profiles (learner_id)
            VALUES ($1)
            RETURNING id
            """,
            learner_id,
        )
        history_id = await connection.fetchval(
            """
            INSERT INTO learner_profile_history (
                learner_profile_id,
                learner_id,
                version,
                observed_event_count,
                change_source
            )
            VALUES ($1, $2, 1, 0, 'system_inference')
            RETURNING id
            """,
            profile_id,
            learner_id,
        )

        with pytest.raises(asyncpg.RaiseError, match="history is immutable"):
            await connection.execute(
                """
                UPDATE learner_profile_history
                SET change_reason = 'changed'
                WHERE id = $1
                """,
                history_id,
            )
    finally:
        await connection.close()


async def test_enum_contract_is_exact() -> None:
    connection = await asyncpg.connect(asyncpg_url())
    try:
        confidence_values = await connection.fetch(
            """
            SELECT enumlabel
            FROM pg_enum
            JOIN pg_type ON pg_type.oid = pg_enum.enumtypid
            WHERE pg_type.typname = 'profile_confidence'
            ORDER BY enumsortorder
            """
        )

        assert [row["enumlabel"] for row in confidence_values] == [
            "low",
            "medium",
            "high",
        ]
    finally:
        await connection.close()
