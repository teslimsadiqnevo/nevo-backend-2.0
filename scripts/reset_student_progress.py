"""Put one test child back to the start without breaking their account.

A child who has been through a demo cannot be demoed again: their mastery is
seeded, the lesson is marked finished, the comprehension gate remembers the
checks they passed. Deleting the account and reseeding loses the sign-in the
console has written down, and deleting too much leaves a child who signs in
and is refused at the door with a 409 - no consent record, no onboarding - and
looks from the console like a broken lesson.

So this draws the line explicitly. What a child did is removed. Who they are,
what they agreed to, which class they are in and the fact that they finished
onboarding all stay. The two lists are below and nothing happens to a table
that is in neither, because a table nobody has classified is a table nobody
has thought about.

Dry run by default. --apply is required to delete anything, and a child
outside the test school needs --i-know-this-is-a-real-child as well: this
destroys a real learning record and cannot be undone.

    python scripts/reset_student_progress.py --student NV-E2E-SS1B-003
    python scripts/reset_student_progress.py --student NV-E2E-SS1B-003 --apply
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from nevo.db.models.account import User

#: The E2E test school. A child here is a fixture and may be reset freely.
TEST_SCHOOL_ID = UUID("c5cd0a8d-043c-4f97-aad2-4a724a877a29")

#: What the child did. All of this goes.
#:
#: Every one of these is keyed by student_id and holds a record of activity,
#: not of entitlement. Mastery is included deliberately: deleting the rows
#: returns the child to the baseline their profile was seeded with, which is
#: the state a fresh child starts a lesson in.
PROGRESS = (
    "lesson_question_attempts",
    "paper_work_evidence",
    "concept_review_evidence",
    "scaffold_problem_logs",
    "post_lesson_processing",
    "lesson_progress",
    "lesson_sessions",
    "student_concept_level_mastery",
    "student_concept_mastery",
    "student_concept_scaffold_states",
    "student_concept_scheduling",
    "adaptation_decisions",
    "probe_responses",
    "out_of_school_learning",
    "offline_downloads",
)

#: Telemetry that cannot be deleted, and does not need to be.
#:
#: signal_events carries a database trigger, signal_events_append_only, that
#: refuses any delete. That is deliberate - the raw record of what a child did
#: is audit evidence - and a reset is not a reason to go round it.
#:
#: It costs the reset nothing. Every read of these events joins through the
#: child's lesson sessions: adaptation context, the accommodation inference
#: and the attention-flag service all select by session_id, and the
#: accommodation repository returns an empty aggregate the moment a child has
#: no sessions. Deleting the sessions therefore orphans the events. They stay
#: for audit and are unreachable from delivery, which is the behaviour a reset
#: wants anyway.
#:
#: Listed here rather than in KEPT so the script can say out loud what it left
#: behind and why, instead of looking like it forgot.
APPEND_ONLY = ("signal_events",)

#: Derived signals about how the child is getting on.
#:
#: Not removed by default, and not because they are hard to remove. The
#: support layer is where a human intervenes: an escalation carries a
#: teacher's own note and the name of the person it was routed to, and the
#: flags are what that note was written about. A routine reset that quietly
#: deletes a teacher's safeguarding note is not a reset, it is data loss.
#:
#: They do go stale once the sessions behind them are gone, which matters for
#: a child being demoed again, so --also-clear-support-flags removes them. It
#: is refused outside the test school at any flag, because nothing here is
#: worth deleting a real concern about a real child over.
SUPPORT = (
    "intervention_recommendations",
    "learner_engagement_anomalies",
    "learner_profile_attention_flags",
    "escalations",
    "attention_flags",
)


#: Who the child is, and what a lesson checks before it will start.
#:
#: Named rather than merely omitted, so that the decision is visible and a
#: reviewer can disagree with it. Touching any of these is how a reset turns
#: into a child who cannot sign in:
#:
#: consent_records          - a lesson refuses a child without a confirmed one
#: learner_profiles         - holds completed onboarding modules and the
#:                            baseline the mastery engine starts from
#: student_class_enrollments- which class the child is in
#: parent_links             - who may see their reports
#: student_onboarding_grants- the link the child first signed in through
#: lesson_assignments       - resetting progress is so the lesson can be done
#:                            again, which means keeping it assigned
#: content_safety_events    - a safety record is not a child's progress
#: student_record_events,
#: learner_profile_history,
#: student_enrollment_history,
#: learner_purge_receipts   - audit; the point of an audit trail is that
#:                            routine operations do not edit it
KEPT = (
    "consent_records",
    "consent_invitations",
    "learner_profiles",
    "learner_profile_history",
    "student_class_enrollments",
    "student_enrollment_history",
    "student_onboarding_grants",
    "parent_links",
    "parent_data_requests",
    "lesson_assignments",
    "content_safety_events",
    "student_record_events",
    "learner_purge_receipts",
    "shared_device_profiles",
    "user_connections",
    "message_threads",
    "age_check_edits",
    "iep_exports",
    "iep_export_shares",
    "export_annotations",
    # A teacher's accommodation decision is an entitlement, not progress.
    "accommodation_changes",
    # Identity and consent.
    "age_checks",
    "consent_refusals",
    # What Nevo spent on this child, which is billing and not theirs to lose.
    "ai_gateway_calls",
)


def _every_student_table() -> set[str]:
    """Tables carrying a student_id, from the models rather than a guess."""
    import importlib
    import pkgutil

    import nevo.db.models as models
    from nevo.db.base import Base

    for found in pkgutil.iter_modules(models.__path__):
        importlib.import_module(f"nevo.db.models.{found.name}")
    return {
        table.name
        for table in Base.metadata.sorted_tables
        if any(column.name == "student_id" for column in table.columns)
    }


def unclassified() -> set[str]:
    """Student-scoped tables this script has an opinion about neither way.

    Checked at every run. A new table holding a child's work would otherwise
    be silently left behind, and a reset that quietly misses something is
    worse than one that refuses.
    """
    return _every_student_table() - set(PROGRESS) - set(SUPPORT) - set(APPEND_ONLY) - set(KEPT)


async def _resolve(session, who: str) -> User:
    try:
        found = await session.get(User, UUID(who))
    except ValueError:
        found = await session.scalar(
            select(User).where(func.lower(User.login_identifier) == who.casefold())
        )
        if found is None:
            found = await session.scalar(
                select(User).where(func.lower(User.admission_number) == who.casefold())
            )
    if found is None:
        raise SystemExit(f"No student matches {who!r} (id, login identifier or admission number)")
    return found


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--student", required=True, help="id, login identifier or admission number")
    parser.add_argument("--apply", action="store_true", help="actually delete; otherwise dry run")
    parser.add_argument(
        "--also-clear-support-flags",
        action="store_true",
        help="also remove attention flags, escalations and recommendations (test school only)",
    )
    parser.add_argument(
        "--i-know-this-is-a-real-child",
        action="store_true",
        help="required to reset a child outside the test school",
    )
    args = parser.parse_args()

    stray = unclassified()
    if stray:
        raise SystemExit(
            "These tables hold a student_id and this script classifies as neither "
            "progress, support nor kept, so it will not run: "
            + ", ".join(sorted(stray))
            + "\nAdd each one to PROGRESS or KEPT in this file, with a reason."
        )

    url = os.environ["DATABASE_URL"].replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url, connect_args={"statement_cache_size": 0})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session:
            student = await _resolve(session, args.student)
            name = " ".join(p for p in (student.first_name, student.last_name) if p)
            print(f"student   {name}  {student.id}")
            print(f"sign in   {student.login_identifier}  admission {student.admission_number}")
            print(f"school    {student.school_id}")
            print()

            if student.school_id != TEST_SCHOOL_ID and not args.i_know_this_is_a_real_child:
                raise SystemExit(
                    f"{name} is not in the test school. Resetting a real child destroys "
                    "their learning record and cannot be undone. Pass "
                    "--i-know-this-is-a-real-child if that is genuinely what you want."
                )

            tables = (*PROGRESS, *SUPPORT) if args.also_clear_support_flags else PROGRESS
            if args.also_clear_support_flags and student.school_id != TEST_SCHOOL_ID:
                raise SystemExit(
                    "--also-clear-support-flags is for test children only. An escalation "
                    "carries a teacher's own note about a real child; it is not progress "
                    "and this script will not delete it."
                )

            counts = {}
            for table in tables:
                counts[table] = await session.scalar(
                    text(f"select count(*) from {table} where student_id = :id"),
                    {"id": student.id},
                )
            total = sum(counts.values())
            for table, count in sorted(counts.items(), key=lambda row: -row[1]):
                if count:
                    print(f"  {table:<36} {count}")
            if not total:
                print("  nothing to remove; this child has no progress recorded")
            if not args.also_clear_support_flags:
                flags = 0
                for table in SUPPORT:
                    flags += await session.scalar(
                        text(f"select count(*) from {table} where student_id = :id"),
                        {"id": student.id},
                    )
                if flags:
                    print()
                    print(
                        f"  {flags} support row(s) left in place (attention flags, "
                        "escalations, recommendations). They will refer to sessions "
                        "that no longer exist. --also-clear-support-flags removes them."
                    )

            kept_counts = {}
            for table in ("consent_records", "student_class_enrollments", "lesson_assignments"):
                kept_counts[table] = await session.scalar(
                    text(f"select count(*) from {table} where student_id = :id")
                    if table != "consent_records"
                    else text("select count(*) from consent_records where subject_user_id = :id"),
                    {"id": student.id},
                )
            print()
            print(f"  keeping: {kept_counts} and the onboarding in learner_profiles")

            for table in APPEND_ONLY:
                held = await session.scalar(
                    text(f"select count(*) from {table} where student_id = :id"),
                    {"id": student.id},
                )
                if held:
                    print(
                        f"  {held} {table} row(s) stay: the table is append-only by "
                        "policy. Every read of them joins through the child's lesson "
                        "sessions, so removing those leaves these unreachable from "
                        "delivery while still on the record."
                    )

            if not args.apply:
                print()
                print(f"dry run: {total} rows across {sum(1 for c in counts.values() if c)} tables")
                print("re-run with --apply to remove them")
                return

        async with sessions.begin() as session:
            removed = 0
            for table in tables:
                result = await session.execute(
                    text(f"delete from {table} where student_id = :id"),
                    {"id": student.id},
                )
                removed += result.rowcount or 0

        async with sessions() as session:
            left = 0
            for table in tables:
                left += await session.scalar(
                    text(f"select count(*) from {table} where student_id = :id"),
                    {"id": student.id},
                )
            check = await session.get(User, student.id)
            consent = await session.scalar(
                text(
                    "select status from consent_records where subject_user_id = :id "
                    "and consent_type = 'data_processing'"
                ),
                {"id": student.id},
            )
            modules = (check.baseline_profile or {}).get("completed_modules") or []
            enrolled = await session.scalar(
                text("select count(*) from student_class_enrollments where student_id = :id"),
                {"id": student.id},
            )

        print()
        print(f"removed   {removed} rows; {left} progress rows remain")
        print(f"status    {check.status}")
        print(f"consent   {consent}")
        print(f"class     {enrolled} enrolment(s)")
        print(f"onboarding {len(modules)} module(s) still complete")
        ready = (
            left == 0
            and consent is not None
            and str(consent).endswith("confirmed")
            and enrolled
            and modules
        )
        print("reset, and this child can still start a lesson" if ready else "CHECK THIS")
        sys.exit(0 if ready else 1)
    finally:
        await engine.dispose()


asyncio.run(main())
