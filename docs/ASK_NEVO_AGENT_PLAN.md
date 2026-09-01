# Ask Nevo: from fixed context to a reasoning assistant

Status: plan. Nothing here is built yet.
Baseline commit: `3e4f5a4`.

## Why it is not intelligent today

Two separate causes. The first is obvious once seen; the second is not, and it
invalidates the naive version of this feature.

### 1. The context is a blob, not a lookup

`SqlAlchemyAskNevoRepository.build_context` assembles a payload from whatever
IDs the frontend supplied in `contextIds`. Nothing else is reachable.

A teacher on the My Classes page asking *"how's Amara Okafor doing?"* sends no
`studentId` — the frontend cannot know which student a free-text name refers
to. So the model receives a context with no student in it and answers
generically. It is not being unintelligent; it has nothing to reason over.

### 2. The model never sees the name

The privacy guard pseudonymises every roster name before the prompt leaves the
building:

```
"how's amara okafor doing?"  →  "how's Learner-B8F12EA8C9 doing?"
```

This is deliberate and is what the NDPA compliance audit rests on. But it means
a naive `find_student(name)` tool cannot work: the model would call it with a
pseudonym that matches no record.

**Any design that ignores this either breaks the tool or breaks the compliance
posture.** Resolving it is the central problem of this work, not a detail.

## Target architecture

### The pseudonym round-trip

Pseudonyms become the model's identifiers. The mapping never leaves the server.

```
teacher asks     "how's Amara Okafor doing?"
  ↓ guard         "how's Learner-B8F1 doing?"        model never sees a real name
  ↓ tool call     get_student_overview("Learner-B8F1")
  ↓ server        resolve pseudonym → student id
                  authorise: may THIS teacher see THIS student?
  ↓ tool result   { learner: "Learner-B8F1", mastery: [...], flags: [...] }
  ↓ model         "Learner-B8F1 is secure on halves but rushes subtraction"
  ↓ rehydrate     pseudonym → display name, on the way out only
teacher sees     "Amara is secure on halves but rushes subtraction"
```

Properties worth stating explicitly:

- The model never receives a real name, in the prompt **or** in a tool result.
- The teacher never sees a pseudonym.
- The compliance claim gets stronger, not weaker: it now holds under tool use.
- The mapping is per-request and in-memory. It is not persisted, so a leaked
  transcript cannot be re-identified from stored state.

`AiPrivacyGuard.pseudonym` is already a deterministic function of the subject
UUID, so the reverse map is built by pseudonymising the candidate set the actor
can see, not by inverting a hash.

### Authorization

**No tool may trust an identifier the model supplied.** The model is an
untrusted caller. Every tool re-derives permission from the actor:

| Actor | May reach |
| --- | --- |
| Student | Themselves only |
| Teacher | Students in classes assigned to them, via `TeacherClassAssignment` |
| SENCo / other admin | Their own school |
| Anyone | Never another school, under any argument |

Reuse `can_access_student` and `require_class_access` from `api/product_common`
rather than reimplementing the chain.

A denied lookup returns a **tool result**, not an exception: `{"error":
"not_permitted"}`. The model then explains it cannot see that student, which is
a better experience than a 500 and keeps the refusal inside the conversation.

Candidate sets are always derived from the actor first, then filtered — never
"look up by id, then check". That ordering makes cross-tenant access
structurally impossible rather than merely checked for.

### Tool catalogue (first cut)

| Tool | Input | Returns |
| --- | --- | --- |
| `find_students` | partial name or pseudonym | matching learners the actor may see |
| `get_student_overview` | pseudonym | profile summary, mastery, recent sessions |
| `list_my_classes` | – | classes the actor teaches or administers |
| `get_class_overview` | class id | roster size, engagement, comprehension |
| `get_recent_flags` | pseudonym or class id | attention flags with evidence |
| `get_lesson_overview` | lesson id | segments, modalities, review state |

Keep the set small. Every tool is prompt surface, and a large catalogue makes
selection worse rather than better.

## Delivery phases

Each phase is independently shippable and leaves the system working.

### Phase 1 — Tool execution layer

`ask_nevo/tools.py`: schemas, executors, the pseudonym map, authorization.
Pure functions over a session and an actor. No model involvement.

Testable end to end without an API key, which is the point of doing it first.

**Done when:** a teacher's actor resolves a pseudonym to a student they teach,
and returns `not_permitted` for one they do not.

### Phase 2 — Tool use in the provider

`ClaudeRestProvider` is text-only. Extend `ProviderRequest`/`ProviderResponse`
to carry `tools` and `tool_use` blocks, and implement the loop: call → execute
requested tools → return results → repeat until `stop_reason != "tool_use"`.

Bound it: max 5 iterations, then answer with what it has. An unbounded loop
against a live model is a cost incident waiting to happen.

Keep it inside the gateway so rate limiting, cost accounting, the audit trail
and the fallback all continue to apply. Do not build a side channel.

**Done when:** a fake provider driving a scripted tool sequence produces the
right result, with no network.

### Phase 3 — Wire Ask Nevo to it

Replace the fixed context blob with a small seed context (who is asking, what
page, which IDs the frontend did supply) plus the tool set. Rehydrate
pseudonyms in the answer before returning.

**Done when:** the screenshot case works — from My Classes, "how's Amara
doing?" returns something specific and correct.

### Phase 4 — Quality

Prompt work, tool descriptions, an eval set of real teacher questions. This is
where "intelligent" is actually won or lost; phases 1–3 only make it possible.

## Testing

- **Authorization is the priority.** Table-driven: every (actor role, target)
  pair, asserting cross-school and cross-class access are impossible.
- **Pseudonym round-trip:** no real name in any outbound payload; no pseudonym
  in any answer returned to a client.
- **Tool loop:** fake provider, scripted sequences. Include the malicious case
  — a model asking for a student it may not see.
- **Regression:** the existing rule-based fallback path must keep working when
  the provider is unavailable.

## Risks

| Risk | Mitigation |
| --- | --- |
| Cost per question rises with tool calls | Cap iterations; keep the catalogue small; the gateway already meters spend |
| Latency: several round trips | Stream the final answer; consider a fast model for tool selection |
| Model invents a pseudonym | Unknown pseudonym returns `not_found`, never a guess |
| A tool leaks a real name into the prompt | One serialisation path for tool results, pseudonymised there, with a test asserting it |
| Prompt injection via lesson content | Tool results are data, never instructions; authorization is server-side so a compromised prompt still cannot widen access |

## Open questions

1. **Should students get tools at all?** A student asking about their own
   progress is reasonable; a student probing what the system knows about them
   is not. Simplest defensible start: teachers and admins only.
2. **Should the answer cite which tools it used?** Useful for teacher trust and
   for debugging a wrong answer. Costs a little response surface.
3. **Streaming.** Tool loops make responses slower; teachers will notice. Worth
   deciding before phase 3 rather than retrofitting.

## What this builds on

Already in place and reused rather than rebuilt:

- `AiPrivacyGuard` — pseudonymisation, now also the identifier scheme
- `can_access_student` / `require_class_access` — the authorization chain
- The AI gateway — audit, cost, rate limiting, fallback
- `ask_nevo/formatting.py` — answers are structured server-side regardless of
  shape, so richer answers need no client change
