"""What an email address currently holds, before anybody clears it.

Yinka's five test addresses, 12 November: "clear each one so I can sign up with
it again, and if any of them owns lessons or classes, or is a school's billing
contact or only admin, skip it and tell me."

This is the read-only half, and it is deliberately separate from anything that
deletes. Run it first. It searches every email-shaped column in the schema
rather than only users.email, because an orphaned invitation or billing
contact blocks a sign-up just as well as an account does, and checking one
table would have reported "clear" while the address was still taken.

    python scripts/inspect_test_email.py a@example.com b@example.com

Nothing is written. The clearing tool is a separate thing, behind the
platform-admin sign-in, limited to test schools and logged.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

#: Reasons an address must not simply be cleared. Each is something another
#: person or a school depends on, so the answer is "skip it and say why".
BLOCKING = (
    ("lessons they created", "select count(*) from lessons where created_by_id = :i"),
    (
        "classes they teach",
        "select count(*) from teacher_class_assignments "
        "where teacher_id = :i and removed_at is null",
    ),
    ("billing contact rows", "select count(*) from billing_contacts where user_id = :i"),
    (
        "schools billing them directly",
        "select count(*) from schools where billing_contact_id in "
        "(select id from billing_contacts where user_id = :i)",
    ),
    (
        "children linked to them as a parent",
        "select count(*) from parent_links where parent_id = :i",
    ),
    ("uploads they requested", "select count(*) from upload_jobs where requested_by_id = :i"),
)


async def _email_columns(connection) -> list[tuple[str, str]]:
    rows = (
        await connection.execute(
            text("""
        select table_name, column_name from information_schema.columns
        where table_schema = 'public'
          and (column_name ilike '%email%' or column_name ilike '%contact%')
          and data_type in ('text', 'character varying')
        order by table_name, column_name
    """)
        )
    ).all()
    return [(row.table_name, row.column_name) for row in rows]


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("emails", nargs="+", help="addresses to look up")
    args = parser.parse_args()
    wanted = [email.strip().casefold() for email in args.emails]

    url = os.environ["DATABASE_URL"].replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url, connect_args={"statement_cache_size": 0})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    blocked: list[str] = []
    try:
        async with sessions() as session:
            connection = await session.connection()
            columns = await _email_columns(connection)

            for email in wanted:
                print(f"\n{email}")
                account = (
                    await connection.execute(
                        text("""
                    select u.id, u.role, u.status, u.first_name, u.last_name,
                           u.school_id, s.name as school
                    from users u left join schools s on s.id = u.school_id
                    where lower(u.email) = :e
                """),
                        {"e": email},
                    )
                ).first()

                if account is not None:
                    name = " ".join(p for p in (account.first_name, account.last_name) if p)
                    print(f"   account   {name or '(no name)'}  {account.role}  {account.status}")
                    print(f"   school    {account.school} ({account.school_id})")
                    reasons = []
                    for label, sql in BLOCKING:
                        count = await connection.scalar(text(sql), {"i": account.id})
                        if count:
                            reasons.append(f"{label}: {count}")
                    if account.school_id and account.role in ("senco_admin", "other_admin"):
                        admins = await connection.scalar(
                            text("""
                            select count(*) from users where school_id = :s
                              and role in ('senco_admin', 'other_admin') and status = 'active'
                        """),
                            {"s": account.school_id},
                        )
                        if admins == 1:
                            reasons.append("the school's only active admin")
                    if reasons:
                        blocked.append(email)
                        print("   SKIP - others depend on this account:")
                        for reason in reasons:
                            print(f"     {reason}")
                    else:
                        print("   holds nothing anybody else depends on")
                else:
                    print("   no account")

                # Everything else carrying the address. An expired login code
                # does not block a sign-up; an open invitation does.
                traces = []
                for table, column in columns:
                    try:
                        found = await connection.scalar(
                            text(f'select count(*) from "{table}" where lower("{column}") = :e'),
                            {"e": email},
                        )
                    except Exception:
                        continue
                    if found:
                        traces.append(f"{table}.{column}: {found}")
                if traces:
                    print("   other traces:")
                    for trace in traces:
                        print(f"     {trace}")
                elif account is None:
                    print("   nothing anywhere - free to sign up as it stands")
    finally:
        await engine.dispose()

    if blocked:
        print(f"\n{len(blocked)} address(es) to skip: {', '.join(blocked)}")
    sys.exit(0)


asyncio.run(main())
