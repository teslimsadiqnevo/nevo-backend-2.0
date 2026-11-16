"""Keep this machine on the Render database's inbound IP allowlist.

The database is reachable from outside Render only by the addresses listed in
its inbound IP rules. That list is what stands between the live data and the
open internet, so it is deliberately narrow - and a narrow list on a home
connection goes stale every time the ISP hands out a new address.

The failure that causes is worth naming, because it does not look like a
permissions problem: an address that is not on the list gets no refusal, it
gets silence, and the connection sits there until it times out. That reads
like the database being down. If a script that worked yesterday now hangs on
connect, run this before looking anywhere else.

    export RENDER_API_KEY=...          # Account Settings -> API Keys
    python scripts/render_db_allowlist.py              # show the rules
    python scripts/render_db_allowlist.py --allow-me   # put this machine on
    python scripts/render_db_allowlist.py --allow 1.2.3.0/24 --description "office"
    python scripts/render_db_allowlist.py --remove 1.2.3.0/24
    python scripts/render_db_allowlist.py --block-all  # no external access

Nothing is written without one of --allow-me, --allow, --remove or
--block-all. The key is read from the environment and never logged.

Render's levels intersect: an address must be permitted by the workspace rules
*and* by the database's own. So this only ever narrows access - it cannot open
the database wider than the workspace already allows.
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import sys
from datetime import UTC, datetime

import httpx

API = "https://api.render.com/v1"

#: The database this manages. A name is resolved to an id, so it keeps working
#: if the database is ever recreated.
DEFAULT_DATABASE = "nevo-backend-db-for-now"

#: Where we ask what our own address is. Two, because the answer is useless if
#: it is wrong and a single provider having a bad day should not write a
#: mistaken rule - if they disagree, we stop rather than guess.
IP_ORACLES = ("https://api.ipify.org", "https://checkip.amazonaws.com")

#: Entries this script wrote for "this machine". Matched on the prefix so a
#: new address replaces the old one instead of the list growing a tail of
#: addresses that stopped being ours months ago.
MINE = "this machine"


class Failed(Exception):
    """Something we should stop for, reported without a traceback."""


def _client(key: str) -> httpx.Client:
    return httpx.Client(
        base_url=API,
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
        timeout=30.0,
    )


def _check(response: httpx.Response, what: str) -> object:
    if response.status_code == 401:
        raise Failed("RENDER_API_KEY was rejected. Create a new key under Account Settings.")
    if response.status_code == 403:
        raise Failed(f"The key is not allowed to {what}. It needs write access to the workspace.")
    if response.status_code >= 400:
        raise Failed(f"Render refused to {what}: {response.status_code} {response.text[:300]}")
    return response.json()


def find_database(client: httpx.Client, wanted: str) -> tuple[str, str]:
    """Return (id, name), accepting either an id or a name."""
    payload = _check(client.get("/postgres", params={"limit": 100}), "list the databases")
    found = []
    for item in payload:  # type: ignore[union-attr]
        db = item.get("postgres", item)
        if wanted in (db.get("id"), db.get("name")):
            found.append((db["id"], db["name"]))
    if not found:
        known = ", ".join(sorted(i.get("postgres", i).get("name", "?") for i in payload))  # type: ignore[union-attr]
        raise Failed(f"No database called {wanted!r}. This key can see: {known or 'none'}")
    if len(found) > 1:
        raise Failed(f"{wanted!r} matches more than one database: {found}. Use the id.")
    return found[0]


def current_rules(client: httpx.Client, db_id: str) -> list[dict[str, str]]:
    payload = _check(client.get(f"/postgres/{db_id}"), "read the database")
    return list(payload.get("ipAllowList") or [])  # type: ignore[union-attr]


def my_address() -> str:
    """This machine's public IPv4, agreed by two independent sources."""
    answers: dict[str, str] = {}
    for url in IP_ORACLES:
        try:
            response = httpx.get(url, timeout=10.0)
            response.raise_for_status()
            answers[url] = response.text.strip()
        except Exception as exc:
            print(f"  could not ask {url}: {type(exc).__name__}", file=sys.stderr)
    if not answers:
        raise Failed("Could not work out this machine's public address. Pass --allow explicitly.")
    distinct = set(answers.values())
    if len(distinct) > 1:
        raise Failed(
            f"The address oracles disagree ({answers}). That usually means a VPN turning over. "
            "Settle the connection, or pass --allow explicitly."
        )
    address = distinct.pop()
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError as exc:
        raise Failed(f"{address!r} is not an address we can use: {exc}") from exc
    if parsed.version != 4:
        raise Failed(f"Render's rules are IPv4 only and this machine reported {address}.")
    return f"{address}/32"


def normalise(cidr: str) -> str:
    """A bare address means that address alone, which is what we want."""
    try:
        return str(ipaddress.ip_network(cidr, strict=False))
    except ValueError as exc:
        raise Failed(f"{cidr!r} is not a CIDR block: {exc}") from exc


def covers(rules: list[dict[str, str]], address: str) -> bool:
    host = ipaddress.ip_network(address, strict=False)
    for rule in rules:
        try:
            if host.subnet_of(ipaddress.ip_network(rule["cidrBlock"], strict=False)):
                return True
        except (ValueError, TypeError):
            continue
    return False


def show(rules: list[dict[str, str]], label: str) -> None:
    print(f"{label}:")
    if not rules:
        print("    (empty - no external connections are accepted)")
        return
    width = max(len(r.get("cidrBlock", "")) for r in rules)
    for rule in sorted(rules, key=lambda r: r.get("cidrBlock", "")):
        block = rule.get("cidrBlock", "?")
        note = rule.get("description", "")
        flag = "  <- everywhere" if block == "0.0.0.0/0" else ""
        print(f"    {block:<{width}}  {note}{flag}")


def apply(client: httpx.Client, db_id: str, rules: list[dict[str, str]]) -> list[dict[str, str]]:
    payload = _check(
        client.patch(f"/postgres/{db_id}", json={"ipAllowList": rules}),
        "update the allowlist",
    )
    return list(payload.get("ipAllowList") or [])  # type: ignore[union-attr]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--database", default=os.environ.get("RENDER_DATABASE", DEFAULT_DATABASE))
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--allow-me", action="store_true", help="put this machine's address on the list"
    )
    action.add_argument("--allow", metavar="CIDR", help="add a specific block")
    action.add_argument("--remove", metavar="CIDR", help="take a block off")
    action.add_argument(
        "--block-all", action="store_true", help="accept no external connections at all"
    )
    parser.add_argument("--description", help="label for the block being added")
    parser.add_argument(
        "--force",
        action="store_true",
        help="go ahead even though the result would shut this machine out",
    )
    args = parser.parse_args(argv)

    key = os.environ.get("RENDER_API_KEY", "").strip()
    if not key:
        raise Failed("Set RENDER_API_KEY. Render dashboard -> Account Settings -> API Keys.")

    with _client(key) as client:
        db_id, name = find_database(client, args.database)
        rules = current_rules(client, db_id)
        print(f"{name}  ({db_id})\n")
        show(rules, "now")

        if not (args.allow_me or args.allow or args.remove or args.block_all):
            here = my_address()
            state = "covered" if covers(rules, here) else "NOT covered"
            print(f"\nthis machine is {here}, which is {state}")
            print("\nnothing changed. Pass --allow-me to put this machine on the list.")
            return 0

        wanted = list(rules)
        if args.block_all:
            wanted = []
        elif args.remove:
            block = normalise(args.remove)
            wanted = [r for r in wanted if normalise(r.get("cidrBlock", "0.0.0.0/32")) != block]
            if len(wanted) == len(rules):
                print(f"\n{block} was not on the list. Nothing to do.")
                return 0
        else:
            block = my_address() if args.allow_me else normalise(args.allow or "")
            note = args.description or (
                f"{MINE} ({datetime.now(UTC):%Y-%m-%d})" if args.allow_me else "added by script"
            )
            if args.allow_me:
                # Drop whatever address this machine had last time.
                wanted = [r for r in wanted if not r.get("description", "").startswith(MINE)]
            wanted = [r for r in wanted if normalise(r.get("cidrBlock", "0.0.0.0/32")) != block]
            wanted.append({"cidrBlock": block, "description": note})

        here = my_address()
        if not args.force and wanted and not covers(wanted, here):
            raise Failed(
                f"That would leave {here} off the list, so this machine could no longer reach "
                "the database and you would have to fix it in the dashboard. Pass --force if "
                "you meant it."
            )
        if not args.force and not wanted and not args.block_all:
            raise Failed("That would empty the list. Pass --block-all if you meant it.")

        print()
        show(wanted, "about to set")
        written = apply(client, db_id, wanted)
        print()
        show(written, "now set")
        if args.block_all:
            print(
                "\nExternal connections are off. Render services still reach it "
                "on the internal host."
            )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Failed as error:
        print(f"\n{error}", file=sys.stderr)
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        raise SystemExit(130) from None
