# Safety v1 source replay, 18 November 2026

## Scope

The saved Food Chains and Separation of Mixtures PDFs were read from the live
database in a read-only transaction and parsed with the active production
`content_parse.default` prompt (MD5
`5f097819e960e519cc2ce05f2859fcfb`) against an isolated local database.
The gateway used v1 safety decisions. No production lesson or safety record was
changed. Optional depth rewrites were omitted; this replay covers source
checking, section generation and generated-output checking, not every later
pipeline phase. Separation of Mixtures was replayed from its saved PDF, not the
earlier failed text upload, whose source blob was unavailable.

## Result

| Source | Attempts | Valid generated-output replays | Generated-output blocks | Excluded attempts |
| --- | ---: | ---: | ---: | --- |
| Food Chains | 10 | 7 | 0 | 3 checker-unavailable errors |
| Separation of Mixtures | 5 | 4 | 0 | 1 parse with no generated-output check |

No exact generated-output failure was reproduced or captured in these runs.
The excluded attempts are not counted as passes. This is a non-reproduction
finding, not evidence that v1 is reliable or that v2 fixes the production
failure. A full staged acceptance run and Lydia's sign-off remain required
before enabling v2. The privacy exception under v1 remains active.

## Configuration finding

The `SAFETY_POLICY_V2_ENABLED` environment variable was present in core
settings but absent from the AI gateway and visual generation settings. The
gateway and image checker therefore stayed on v1 even if the flag was set on
their workers. The settings are now wired and covered by focused tests; the
flag still defaults to false.
