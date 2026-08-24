# Multi-Signal Adaptation Confirmation

Hardened in-lesson adaptation triggers so no single passive signal can fire an adaptation.

## Rules

- At least 3 aligned signal observations are required.
- Signals must span at least 2 categories.
- Confidence must be at least 0.6 for the first adaptation.
- Confidence must be at least 0.7 after an earlier modality shift in the session.
- Response time is never enough by itself; it only counts when paired with accuracy or comprehension movement.

## Signal Evidence

Adaptation candidates now carry `trigger_signals`, with each signal including:

- category
- name
- confidence

The `/api/intelligence/adapt` response exposes this evidence for frontend signal logging. Suppressed adaptation logs also include the same evidence and confidence in `signal_events.event_data`.
