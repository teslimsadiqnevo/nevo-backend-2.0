# Ops palette audit

## Required operational token

The old success token and mint status colour are not allowed in ops UI surfaces.
Operational or on-track indicators must use:

```css
rgba(247, 241, 230, 0.45)
```

This is Cream at 45 percent opacity from the calm violet system.

## Repo audit

The committed backend repo does not currently include the Nevo Ops Frame or
J1-J12 design source files. A regression test now scans committed ops/J design
files when they are added and fails on the old green/red/amber operational
tokens.

## Manual verification for imported design files

When the Nevo Ops Frame and J1-J12 files are added to this repo, launch each ops
screen and verify that no green, red, or amber renders. The ops event feed,
teacher session detail, and admin dashboard must show only functional wording
from derived session state, never raw touch signals.
