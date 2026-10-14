# SCRUM-125: Teacher Ask Nevo history

The existing Ask Nevo thread list and transcript reads remain scoped to the asking account. Other teachers and administrators cannot read somebody else's conversations. Lists are newest first and capped at 50 rows, with a title derived from the question, conversation id and timestamps.

Teacher conversations expire 90 days after creation. List reads exclude expired conversations immediately; transcript reads return no record; model history reads return no prior turns; and appending to an expired conversation is refused. The existing scheduled daily retention sweep physically removes the expired thread and its cascading messages. The sweep drains all expired batches rather than leaving everything after the first 200 until another day.

Student, parent and administrator conversation retention remains governed by the school's existing policy. No database migration is needed.
