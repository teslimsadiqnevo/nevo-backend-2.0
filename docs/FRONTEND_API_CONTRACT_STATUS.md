# Frontend API contract status

Updated: 2026-08-30

## OpenAPI response models

Every JSON endpoint now declares a named response model. Swagger no longer emits anonymous `object` or anonymous `array<object>` response bodies. This includes the product administration, school access, learning product, messaging, notifications, intelligence, analytics, upload, and session-management routes.

The response models are enforced by FastAPI at runtime. A backend response that drifts from its documented fields now fails validation instead of silently changing the frontend contract.

## Canonical casing

Camel case is canonical for the v2 product contracts under `/api` and `/api/v1`.

The mixed class-roster response has been corrected. `GET /api/v1/classes/{class_id}/students` now returns `studentId`, `firstName`, `lastName`, `displayName`, `loginIdentifier`, `profileStatus`, and `latestSessionAt`.

The original authentication endpoints retain their existing snake-case responses as compatibility contracts. They will not be renamed silently. A future auth casing migration must use a new version or an announced deprecation window.

## Previously empty shapes

The following fields are now explicitly present in OpenAPI even when their values are empty or null:

- Classes and teacher dashboard class rows: `yearGroup: string | null`.
- Student rows and details: `ageBand: string | null`.
- Assignment rows: `classId: uuid | null` and `dueAt: datetime | null`.
- Class rows and details: `archivedAt: datetime | null`.
- Personal settings: `preferences: object`.
- School details: `profile: object` and `academicConfig: object`.
- Notification preferences: `{ category, inApp, email }[]`.

## Learner intelligence shapes

`GET /api/v1/students/{student_id}/profile` returns:

```json
{
  "student": {
    "id": "uuid",
    "firstName": "string|null",
    "lastName": "string|null",
    "ageBand": "string|null"
  },
  "profile": {
    "version": 1,
    "observedEventCount": 0,
    "lastEvaluatedAt": "datetime|null"
  },
  "openFlagCount": 0
}
```

`profile` is `null` until the student has an observed learner profile.

`GET /api/intelligence/flags` returns:

```json
[
  {
    "id": "uuid",
    "studentId": "uuid",
    "flagType": "engagement_decline|sudden_change",
    "description": "Functional, non-diagnostic text",
    "generatedAt": "datetime",
    "acknowledged": false,
    "evidenceSeries": [61.0, 48.0, 39.0],
    "actionTargets": ["view_student", "open_recommendation"]
  }
]
```

## Route readiness

The additional routes are real product subsystems, not speculative Swagger placeholders. Their handlers persist or query PostgreSQL and enforce authenticated school context. This includes class and student CRUD, invitations, session management, staged lesson uploads, notification preferences, analytics, and learner-intelligence projections.

Some integrations still require external deployment credentials to operate against third parties: SMTP delivery, Microsoft/Google directory access, and Anthropic. Missing credentials produce an explicit unavailable or needs-attention state; they do not return invented success data.

## Teacher console additions

- `GET /api/v1/lessons/{lessonId}` now includes both `modules` and segment
  `needsReview` / `reviewReasons`.
- `GET /api/v1/teachers/me/home` returns `classLearningPulse` and
  `recentActivity`.
- `GET /api/v1/classes/{classId}/students` includes functional `observations`
  and `seatContext`.
- `GET /api/v1/lessons/{lessonId}/class-progress?classId=...` returns segment
  completion, average time, slowdown counts, and a functional slowdown note.
- `PUT /api/v1/uploads/{uploadId}/structure` accepts a typed module document.
- `POST /api/v1/uploads/{uploadId}/retry-pages` reparses selected PDF pages.
- `POST /api/v1/uploads/import` downloads from a configured Google Drive or
  OneDrive connection and enters the same staged parsing flow.
- Teacher-facing learner profiles do not contain working-memory, attention-span,
  or engine-configuration values.
- `GET /api/conversation-evidence/student/{studentId}` is aggregate-only. Its
  `privacy` value is `aggregate_only` or `withheld_below_minimum`; category and
  helpfulness aggregates are withheld below three interactions.
- Lesson progress positions are zero-based (`positionBase: 0`) and include
  one-based `moduleNumber` and `segmentNumber` for display.
- Assignments support distinct `availableFrom` and `dueAt` values. Student reads
  hide assignments until `availableFrom`.
- Lesson summaries include `subject` and `assignmentCount`; message threads
  include `className`, `unread`, and `unreadCount`.

## Swagger verification

Swagger groups routes by their product domain: Authentication, Product Access, School Administration, Learning Product, Messaging, Notifications, Intelligence, Content, Billing, SSO, Exports, and related operational domains. There is intentionally no `Frontend Unblockers` route group.
