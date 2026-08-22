# Admin adaptation event log

## Scope

The school admin adaptation log is exposed through:

- `GET /api/admin/adaptation-log`

The endpoint requires the admin `oversight` scope and a school context.

## Filters

- `classId`
- `studentId`
- `lessonId`
- `dateFrom`
- `dateTo`
- `limit`
- `offset`

## Rows

Each row contains the fields the admin UI table needs:

- time via `timestamp`
- first-name-only student display via `studentFirstName`
- lesson title
- plain-language trigger
- plain-language adaptation shift

The endpoint reads existing adaptation events from `signal_events`, including
modality suggestions/switches, simplification, expansion, slower pacing, and
break suggestions.
