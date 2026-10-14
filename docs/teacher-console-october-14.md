# Teacher console contract updates: 14 October 2026

- B-9: `GET /api/v1/students/{id}/profile` allows teachers of the student's classes without Learning Support. The class access check remains enforced. Adaptation history retains its Learning Support gate.
- B-10: `POST /api/intelligence/flags/{id}/acknowledge` allows the student's class teachers without Learning Support. Repeated acknowledgement preserves the first acknowledgement. Escalation acknowledgement remains separately gated.
- B-7: PIN reset requests notify assigned teachers using `/teacher/students/{studentId}/clear-pin?class={classId}`. Administrator notifications retain their admin destination.
- B-8: Both message creation and thread reply create teacher notifications linking to `/teacher/connect?thread={threadId}`. Student-directed teacher replies link to `/student/connect?thread={threadId}`.
- B-4: `GET /api/v1/escalations` includes concerns for pupils in the teacher's assigned classes, regardless of which teacher raised them. Existing acknowledgement fields remain available.
- B-6: Teacher Home's `classLearningPulse` adds `engagementLabel`, `comprehensionLabel`, and `focusLabel`. Values are `Steady`, `Mixed`, `May benefit from support`, or `Still gathering a picture`. The backend owns their boundaries; the client renders the returned text.
- B-2: `POST /api/v1/students/{studentId}/admin-support-request` accepts an optional JSON body `{ "note": "..." }`. The note is limited to 2,000 characters and included in the administrator notification. Requests without a body remain valid. Repeating an outstanding request does not duplicate its notification or replace its note.
- B-3: Class roster rows add `adminSupportRequestOpen` and nullable `adminSupportRequestedAt`. Open means at least one administrator notification for that request remains unread and unarchived. The timestamp is the earliest outstanding notification time. Reading every notification, or archiving them, clears this state; it does not represent a separate support-case resolution workflow.

These changes use existing tables and require no database migration.
