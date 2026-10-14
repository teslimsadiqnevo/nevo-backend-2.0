# SCRUM-233 / SCRUM-236

Reading chunks are generated on the server at ingest and stored on `lesson_segments.reading_chunks`. Online lesson detail and offline packages expose ordered `readingChunks` with `id`, `sequenceOrder`, `text`, `startOffset`, and `endOffset`.

Chunk boundaries follow paragraph breaks. A single-paragraph passage uses sentence boundaries. No character or word budget chooses the boundaries. Identical unchanged prose keeps its id when processed again; repeated copies within a segment have distinct occurrence ids. Changing the prose or its meaning boundaries may create a new chunk identity. Existing stored chunks are preserved until the lesson is deliberately reprocessed.

Clients send `reading_chunk_viewed` through the existing signal ingestion endpoint with `segmentId`, `chunkId`, `action` (`entered` or `passed`), `formFactor` (`phone`, `tablet`, `desktop`), and optional `durationMs`. The client never sends a re-read count.

The backend counts an `entered` event only after a `passed` event for that same learner, session, device type, and chunk. Additional visibility events do not count again until the chunk is passed again. Another session or device type does not inherit the previous session's passed state.

Teacher lesson progress exposes `chunkRereads`: `chunkId`, `rereadCount`, and nullable `timeInChunkMs`. With no return evidence the list is empty. Recorded durations are milliseconds.

No database migration is required; the chunk column and event type already exist. This change corrects the chunking policy and the attribution calculation.
