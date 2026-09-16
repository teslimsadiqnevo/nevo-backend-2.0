"""Fill a tenant with the mixtures and thresholds the console is never tested at.

A tidy tenant of thirty students renders every screen and proves almost
nothing. The bugs this console has shipped all lived in the gap between a
number and the right number: a count capped at a page boundary, a count of
flags rendered under the word "students", an absent value rendered as a zero.
None of them is visible unless the data crosses the boundary that triggers it,
so the shapes here are deliberately lopsided.

    python scripts/seed_e2e_tenant.py --school-code NEVO-E2E

Runs against DATABASE_URL. Every id is derived from the school code, so
running it twice updates the same rows rather than doubling them. It refuses
to touch a school code it did not create unless you pass --allow-existing.
"""

from __future__ import annotations

import argparse
import asyncio
import random
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import NAMESPACE_DNS, UUID, uuid5

from sqlalchemy import select

from nevo.auth.config import AuthSettings
from nevo.auth.wiring import build_credential_hasher
from nevo.core.config import get_settings
from nevo.db.models.account import (
    Class,
    ConsentRecord,
    School,
    StudentClassEnrollment,
    User,
)
from nevo.db.models.attention_flag import AttentionFlag
from nevo.db.models.billing import (
    BillingPaymentMethod,
    BillingSubscriptionTier,
    Contract,
    Invoice,
)
from nevo.db.models.consent import (
    ConsentInvitation,
    ConsentNotificationOutbox,
    ParentLink,
)
from nevo.db.models.content import Lesson
from nevo.db.models.learner_profile import LearnerProfile
from nevo.db.models.permission import Admin, AdminScopeAssignment
from nevo.db.models.product import ParentDataRequest
from nevo.db.models.signal_event import LessonSession, SignalEvent
from nevo.db.models.sso import RosterSyncIssue, RosterSyncRun, SchoolSsoConfiguration
from nevo.db.models.teacher_assignment import TeacherClassAssignment
from nevo.db.session import create_engine, create_session_factory
from nevo.domain.accounts.vocabulary import (
    AuthMethod,
    ConsentMethod,
    ConsentStatus,
    ConsentType,
    RosterSyncStatus,
    SsoConnectionStatus,
    SsoProvider,
    UserRole,
    UserStatus,
)
from nevo.domain.attention_flags.vocabulary import AttentionFlagType
from nevo.domain.billing.vocabulary import (
    ContractStatus,
    InvoiceStatus,
    PaymentSource,
    PricingCurrency,
)
from nevo.domain.consent.vocabulary import (
    ConsentConfirmationSource,
    ParentContactMethod,
    ParentRightType,
)
from nevo.domain.intelligence.vocabulary import LessonSourceType
from nevo.domain.learner_profiles.vocabulary import (
    ChannelPreferenceStrength,
    ConfidenceLevel,
    ProcessingChannelPreference,
)
from nevo.domain.permissions.vocabulary import PermissionScope
from nevo.domain.signal_events.vocabulary import (
    LessonCompletionStatus,
    SignalEventType,
)

NOW = datetime.now(UTC)

#: Shared across every staff account in the tenant. This is seeded test data
#: in a test school - there is nothing here worth protecting, and one password
#: everybody knows beats five nobody can find.
PASSWORD = "NevoE2E#2026!"
#: Not a .test or .example domain: the API validates emails properly and
#: rejects reserved TLDs, so accounts seeded under one cannot sign in.
EMAIL_DOMAIN = "e2e.nevolearning.com"
STUDENT_PIN = "246810"

# Yinka's thresholds, named so a reader can see which ask each one answers.
CONSENT_MIX = {
    ConsentStatus.CONFIRMED: 20,
    ConsentStatus.PENDING: 8,
    ConsentStatus.NOT_SENT: 8,
    ConsentStatus.WITHDRAWN: 3,
}
STUDENTS_WITH_NO_CONSENT_ROW = 1
FLAGGED_STUDENTS = 8
TOTAL_FLAGS = 12
#: The adaptation log caps limit at 100, so three pages is the smallest number
#: that exercises the paging loop rather than exiting on a short first page.
ADAPTATION_EVENTS = 250
ADAPTATION_STUDENTS = 15
ADAPTATION_WINDOW_DAYS = 7

ADAPTATION_TYPES = [
    SignalEventType.SIMPLIFY_TRIGGER,
    SignalEventType.EXPAND_TRIGGER,
    SignalEventType.SLOWER_TRIGGER,
    SignalEventType.BREAK_SUGGESTED,
    SignalEventType.MODALITY_SUGGESTION_SHOWN,
    SignalEventType.MODALITY_SUGGESTION_ACCEPTED,
    SignalEventType.MODALITY_SWITCH_OUTCOME,
    SignalEventType.MODALITY_MANUAL_SWITCH,
]

FIRST_NAMES = [
    "Adaeze",
    "Musa",
    "Ngozi",
    "Chidi",
    "Amaka",
    "Tunde",
    "Zainab",
    "Emeka",
    "Folake",
    "Ibrahim",
    "Chioma",
    "Segun",
    "Halima",
    "Obinna",
    "Yewande",
    "Kelechi",
    "Aisha",
    "Bayo",
    "Nneka",
    "Sadiq",
]
LAST_NAMES = [
    "Okafor",
    "Bello",
    "Adeyemi",
    "Nwosu",
    "Abubakar",
    "Eze",
    "Lawal",
    "Chukwu",
    "Danjuma",
    "Oyelaran",
]


class Seeder:
    def __init__(self, session, *, school_code: str, hasher) -> None:
        self.session = session
        self.school_code = school_code
        self.hasher = hasher
        self.random = random.Random(school_code)
        self.summary: dict[str, int] = {}

    def id_for(self, key: str) -> UUID:
        """Deterministic, and namespaced by school so two tenants never collide."""
        return uuid5(NAMESPACE_DNS, f"nevo-e2e:{self.school_code}:{key}")

    def name_for(self, index: int) -> tuple[str, str]:
        return (
            FIRST_NAMES[index % len(FIRST_NAMES)],
            LAST_NAMES[(index // len(FIRST_NAMES)) % len(LAST_NAMES)],
        )

    async def upsert(self, model, item_id: UUID, **values):
        existing = await self.session.get(model, item_id)
        if existing is None:
            key = "contract_id" if model is Contract else "id"
            existing = model(**{key: item_id}, **values)
            self.session.add(existing)
        else:
            for field, value in values.items():
                setattr(existing, field, value)
        return existing

    async def insert_if_missing(self, model, item_id: UUID, **values) -> None:
        """For rows the database refuses to let anyone update.

        signal_events is append-only and enforces it with a rule, so the
        ordinary upsert fails on a second run. A signal that already exists is
        already right - it was derived from the same seed.
        """

        if await self.session.get(model, item_id) is None:
            self.session.add(model(id=item_id, **values))

    def note(self, what: str, count: int) -> None:
        self.summary[what] = count

    # ---------------------------------------------------------------- school

    async def school(self) -> School:
        school = await self.session.scalar(
            select(School).where(School.school_code == self.school_code)
        )
        if school is None:
            school = School(
                id=self.id_for("school"),
                name="Nevo E2E School",
                school_code=self.school_code,
                school_url_slug=self.school_code.lower(),
            )
            self.session.add(school)
            await self.session.flush()
        return school

    # -------------------------------------------------------------- teachers

    async def teachers(self, school: School) -> list[User]:
        """Three shapes, because each drives a different screen state."""

        shapes = [
            ("busy", UserStatus.ACTIVE, "A teacher holding four classes"),
            ("invited", UserStatus.INVITED, "Invited and never joined"),
            ("sso", UserStatus.ACTIVE, "Arrived through the identity provider"),
            ("spare", UserStatus.ACTIVE, "Somebody to reassign a class to"),
        ]
        people = []
        for index, (slug, status, _) in enumerate(shapes):
            first, last = self.name_for(index + 40)
            people.append(
                await self.upsert(
                    User,
                    self.id_for(f"teacher:{slug}"),
                    school_id=school.id,
                    role=UserRole.TEACHER,
                    auth_method=AuthMethod.EMAIL_PASSWORD,
                    first_name=first,
                    last_name=last,
                    email=f"teacher.{slug}@{EMAIL_DOMAIN}",
                    status=status,
                    # Invited teachers have no credential yet - that is what
                    # makes them the "invited but not joined" state.
                    password_hash=(
                        None
                        if status is UserStatus.INVITED
                        else self.hasher.hash_password(PASSWORD)
                    ),
                )
            )
        await self.session.flush()
        self.note("teachers", len(people))
        return people

    async def admin(self, school: School) -> User:
        """Somebody for a school-collected consent to be attributed to.

        The consent table refuses a confirmed record that does not say who
        confirmed it, which is the right constraint and means a seeded tenant
        needs a real admin rather than a null.
        """

        person = await self.upsert(
            User,
            self.id_for("admin"),
            school_id=school.id,
            role=UserRole.SENCO_ADMIN,
            auth_method=AuthMethod.EMAIL_PASSWORD,
            first_name="Ify",
            last_name="Okonkwo",
            email=f"admin@{EMAIL_DOMAIN}",
            status=UserStatus.ACTIVE,
            password_hash=self.hasher.hash_password(PASSWORD),
        )
        await self.session.flush()

        # A senco_admin row is not enough on its own. Every admin screen sits
        # behind a scope, so without these the tenant renders 403 everywhere
        # and none of the seeded data is reachable.
        record = await self.upsert(
            Admin,
            self.id_for("admin-record"),
            user_id=person.id,
            school_id=school.id,
            created_by_user_id=person.id,
        )
        await self.session.flush()
        for scope in PermissionScope:
            await self.upsert(
                AdminScopeAssignment,
                self.id_for(f"admin-scope:{scope.value}"),
                admin_id=record.id,
                scope=scope,
                granted_by_user_id=person.id,
                revoked_at=None,
            )
        await self.session.flush()
        self.note("admin scopes granted", len(list(PermissionScope)))
        return person

    async def parent_for(self, school: School, index: int) -> User:
        """A parent, because only a parent can withdraw."""

        person = await self.upsert(
            User,
            self.id_for(f"parent:{index}"),
            school_id=school.id,
            role=UserRole.PARENT_GUARDIAN,
            auth_method=AuthMethod.EMAIL_PASSWORD,
            first_name="Parent",
            last_name=f"Of{index}",
            email=f"parent{index}@{EMAIL_DOMAIN}",
            status=UserStatus.ACTIVE,
        )
        await self.session.flush()
        return person

    # --------------------------------------------------------------- classes

    async def classes(self, school: School, teachers: list[User]) -> list[Class]:
        busy, invited, sso, spare = teachers
        # name, year, archived, [(teacher, role)]
        shapes: list[tuple[str, str, bool, list[tuple[User, str]]]] = [
            ("JSS 1A", "JSS 1", False, [(busy, "primary")]),
            ("JSS 1B", "JSS 1", False, [(busy, "primary"), (spare, "co_teacher")]),
            ("JSS 2A", "JSS 2", False, [(busy, "primary")]),
            ("JSS 2B", "JSS 2", False, [(busy, "primary")]),
            ("JSS 3A", "JSS 3", False, [(sso, "primary")]),
            ("JSS 3B", "JSS 3", False, []),  # the "No teacher yet" state
            ("SS 1A", "SS 1", False, [(invited, "primary")]),
            ("SS 2A (2025/26)", "SS 2", True, [(spare, "primary")]),  # archived
        ]
        made = []
        for index, (name, year, archived, staffing) in enumerate(shapes):
            item = await self.upsert(
                Class,
                self.id_for(f"class:{name}"),
                school_id=school.id,
                name=name,
                year_group=year,
                class_code=f"{self.school_code}-{index + 1:02d}",
                archived_at=NOW - timedelta(days=90) if archived else None,
            )
            made.append(item)
            await self.session.flush()
            for role_index, (teacher, role) in enumerate(staffing):
                await self.upsert(
                    TeacherClassAssignment,
                    self.id_for(f"assignment:{name}:{role}"),
                    school_id=school.id,
                    teacher_id=teacher.id,
                    class_id=item.id,
                    role=role,
                    source="manual",
                    # Months apart, so the assignment dates on class and
                    # teacher detail are visibly different from each other.
                    assigned_at=NOW - timedelta(days=30 * (index + 1) + role_index * 14),
                )
        await self.session.flush()
        self.note("classes", len(made))
        self.note("archived classes", sum(1 for c in made if c.archived_at))
        return made

    # -------------------------------------------------------------- students

    async def students(
        self,
        school: School,
        classes: list[Class],
        admin: User,
    ) -> list[User]:
        """Forty learners across every consent state, plus one with no record.

        The mixture is the point. withoutRecordedConsent counts everything but
        confirmed; withdrawnCount counts withdrawals alone. On a uniform
        tenant those two coincide and a conflation bug ships unnoticed.
        """

        teaching = [item for item in classes if item.archived_at is None]
        plan: list[ConsentStatus | None] = []
        for status, count in CONSENT_MIX.items():
            plan.extend([status] * count)
        plan.extend([None] * STUDENTS_WITH_NO_CONSENT_ROW)

        made = []
        for index, status in enumerate(plan):
            first, last = self.name_for(index)
            withdrawn = status is ConsentStatus.WITHDRAWN
            student = await self.upsert(
                User,
                self.id_for(f"student:{index}"),
                school_id=school.id,
                role=UserRole.STUDENT,
                auth_method=AuthMethod.PIN,
                first_name=first,
                last_name=f"{last}{index}",
                login_identifier=f"NV-{self.school_code[-3:]}{index:03d}",
                age_band="11-14",
                # A withdrawal suspends the learner, so the roster has to show
                # one that is deactivated rather than merely flagged.
                status=UserStatus.DEACTIVATED if withdrawn else UserStatus.ACTIVE,
                deactivated_at=NOW - timedelta(days=3) if withdrawn else None,
                pin_hash=self.hasher.hash_pin(STUDENT_PIN),
            )
            made.append(student)
            await self.session.flush()

            await self.upsert(
                StudentClassEnrollment,
                self.id_for(f"enrolment:{index}"),
                student_id=student.id,
                class_id=teaching[index % len(teaching)].id,
            )
            if status is None:
                # Deliberately no row: the student the compliance screen sees
                # as having no consent record at all.
                continue
            if status is ConsentStatus.PENDING:
                # "Pending" means we asked and are waiting. The API refuses to
                # report it without an invitation that was actually sent,
                # which is right - a child nobody wrote to is not pending - so
                # the seed has to create the request, not just the record.
                await self.consent_request(school, student, index, admin)
            # A confirmed or withdrawn record has to say who decided it and
            # how. Only pending and not_sent leave those empty.
            decided = status in {ConsentStatus.CONFIRMED, ConsentStatus.WITHDRAWN}
            parent = await self.parent_for(school, index) if withdrawn else None
            await self.upsert(
                ConsentRecord,
                self.id_for(f"consent:{index}"),
                subject_user_id=student.id,
                consent_type=ConsentType.DATA_PROCESSING,
                status=status,
                confirmation_source=(
                    (
                        ConsentConfirmationSource.PARENT
                        if withdrawn
                        else ConsentConfirmationSource.SCHOOL
                    )
                    if decided
                    else None
                ),
                confirmed_via=ConsentMethod.DIGITAL if decided else None,
                confirmed_at=NOW - timedelta(days=20) if decided else None,
                confirmed_by_admin_id=admin.id if decided and not withdrawn else None,
                confirmed_by_parent_id=parent.id if parent else None,
                last_actor_user_id=parent.id if parent else admin.id if decided else None,
                last_changed_at=NOW - timedelta(days=self.random.randint(1, 30)),
                last_channel="parent_portal" if withdrawn else "school_office",
            )
        await self.session.flush()
        for status, count in CONSENT_MIX.items():
            self.note(f"students {status.value}", count)
        self.note("students with no consent row", STUDENTS_WITH_NO_CONSENT_ROW)
        self.note("students", len(made))
        return made

    async def consent_request(
        self,
        school: School,
        student: User,
        index: int,
        admin: User,
    ) -> None:
        """The parent link, the invitation and the message that was sent."""

        link = await self.upsert(
            ParentLink,
            self.id_for(f"parent-link:{index}"),
            school_id=school.id,
            student_id=student.id,
            parent_name=f"Parent of {student.first_name}",
            parent_contact=f"parent{index}@{EMAIL_DOMAIN}",
            contact_method=ParentContactMethod.EMAIL,
        )
        await self.session.flush()
        invitation = await self.upsert(
            ConsentInvitation,
            self.id_for(f"consent-invitation:{index}"),
            parent_link_id=link.id,
            school_id=school.id,
            student_id=student.id,
            token_digest=f"seed-digest-{self.id_for(f'consent-invitation:{index}')}",
            requested_by_user_id=admin.id,
            created_at=NOW - timedelta(days=6),
            expires_at=NOW + timedelta(days=8),
        )
        await self.session.flush()
        await self.upsert(
            ConsentNotificationOutbox,
            self.id_for(f"consent-outbox:{index}"),
            invitation_id=invitation.id,
            contact_method=ParentContactMethod.EMAIL,
            destination=f"parent{index}@{EMAIL_DOMAIN}",
            consent_url=f"https://app.nevolearning.com/consent/seed-{index}",
            status="sent",
            sent_at=NOW - timedelta(days=6),
        )

    async def rights_requests(self, students: list[User], school: School) -> None:
        """A few rights actually exercised, so the log is not an empty state.

        D22b renders this screen. With no rows it only ever shows the empty
        case, which is the one case that was already covered.
        """

        withdrawn = [s for s in students if s.status is UserStatus.DEACTIVATED]
        kinds = [
            ParentRightType.WITHDRAW_CONSENT,
            ParentRightType.OBJECT,
            ParentRightType.REQUEST_DATA,
        ]
        made = 0
        for index, student in enumerate(withdrawn):
            parent = await self.parent_for(school, index)
            for kind_index, kind in enumerate(kinds[: index + 1]):
                await self.upsert(
                    ParentDataRequest,
                    self.id_for(f"right:{index}:{kind.value}"),
                    student_id=student.id,
                    parent_id=parent.id,
                    request_type=kind.value,
                    # Half carry a reason, so reasonRecorded is not uniform.
                    reason=(
                        "We are moving school at the end of term." if kind_index % 2 == 0 else None
                    ),
                    status="open" if kind_index else "resolved",
                    resolved_at=None if kind_index else NOW - timedelta(days=1),
                )
                made += 1
        await self.session.flush()
        self.note("parent rights exercised", made)

    async def learner_profiles(self, students: list[User]) -> None:
        """Give the tenant children who learn in different ways.

        Every learner looked identical to the adaptation engine: forty
        students and one profile, with every preference null. Nothing that
        reads a preference had anything to show, so the modality surfaces were
        only ever seen in their empty state - a screen saying "works better
        with audio" cannot be wrong if no learner ever prefers audio.

        Real profiles are inferred from observed signals over weeks. These are
        written directly, which is what a test tenant is for, and the
        undetermined ones matter as much as the decided ones: a child nobody
        has enough evidence about is the ordinary case at the start of term.
        """

        # (how many, channel, the dimension that carries it, confidence)
        shapes: list[tuple[int, ProcessingChannelPreference, str, ConfidenceLevel]] = [
            (8, ProcessingChannelPreference.AUDITORY, "auditory", ConfidenceLevel.HIGH),
            (8, ProcessingChannelPreference.VISUAL, "visual_spatial", ConfidenceLevel.HIGH),
            (4, ProcessingChannelPreference.AUDITORY, "auditory", ConfidenceLevel.LOW),
            (4, ProcessingChannelPreference.VISUAL, "visual_spatial", ConfidenceLevel.LOW),
            (
                4,
                ProcessingChannelPreference.INTERACTIVE,
                "interactive_kinesthetic",
                ConfidenceLevel.MEDIUM,
            ),
            (3, ProcessingChannelPreference.TEXTUAL, "reading_writing", ConfidenceLevel.MEDIUM),
            (3, ProcessingChannelPreference.MULTIMODAL, "visual_spatial", ConfidenceLevel.MEDIUM),
        ]
        plan: list[tuple[ProcessingChannelPreference, str, ConfidenceLevel] | None] = []
        for count, channel, dimension, confidence in shapes:
            plan.extend([(channel, dimension, confidence)] * count)

        learners = [item for item in students if item.status is UserStatus.ACTIVE]
        made = 0
        for index, learner in enumerate(learners):
            shape = plan[index] if index < len(plan) else None
            if shape is None:
                # Nobody has watched this child long enough to say anything.
                continue
            channel, dimension, confidence = shape
            # Every dimension is weak unless it is the one this learner leans on.
            values: dict[str, object] = {}
            for name in (
                "visual_spatial",
                "auditory",
                "reading_writing",
                "interactive_kinesthetic",
            ):
                leaning = name == dimension
                values[f"{name}_preference"] = (
                    ChannelPreferenceStrength.STRONG
                    if leaning and confidence is ConfidenceLevel.HIGH
                    else ChannelPreferenceStrength.MODERATE
                    if leaning
                    else ChannelPreferenceStrength.LOW
                )
                values[f"{name}_preference_confidence"] = (
                    confidence if leaning else ConfidenceLevel.LOW
                )
            # Keyed on the learner, not on our own id: a child who has taken a
            # lesson already has a profile the engine made, and learner_id is
            # unique, so writing a second one fails.
            existing = await self.session.scalar(
                select(LearnerProfile).where(LearnerProfile.learner_id == learner.id)
            )
            await self.upsert(
                LearnerProfile,
                existing.id if existing else self.id_for(f"profile:{index}"),
                learner_id=learner.id,
                version=1,
                observed_event_count=40 + index * 3,
                last_evaluated_at=NOW - timedelta(days=index % 5),
                processing_channel_preference=channel,
                processing_channel_preference_confidence=confidence,
                # 1 to 5 scales, kept plausible rather than uniform.
                cognitive_load_threshold=3 + (index % 3) - 1,
                cognitive_load_threshold_confidence=ConfidenceLevel.MEDIUM,
                processing_speed=2 + (index % 4),
                processing_speed_confidence=ConfidenceLevel.MEDIUM,
                working_memory_capacity=2 + (index % 3),
                working_memory_capacity_confidence=ConfidenceLevel.LOW,
                attention_span=12 + (index % 6) * 4,
                attention_span_confidence=ConfidenceLevel.MEDIUM,
                performance_sensitivity=2 + (index % 4),
                performance_sensitivity_confidence=ConfidenceLevel.LOW,
                **values,
            )
            made += 1
        await self.session.flush()
        self.note("learner profiles", made)
        self.note("  clearly auditory", 8)
        self.note("  clearly visual", 8)
        self.note("  leaning, low confidence", 8)
        self.note("  no profile at all", max(len(learners) - made, 0))

    # ----------------------------------------------------------------- flags

    async def flags(self, students: list[User]) -> None:
        """Twelve flags over eight children, so the two numbers differ.

        The Overview says "N students have a flag nobody has marked as seen",
        which is a count of children. Give every child exactly one flag and a
        bug that counts flags instead reads identically.
        """

        subjects = [s for s in students if s.status is UserStatus.ACTIVE][:FLAGGED_STUDENTS]
        made = 0
        for index in range(TOTAL_FLAGS):
            student = subjects[index % len(subjects)]
            acknowledged = index % 3 == 0
            await self.upsert(
                AttentionFlag,
                self.id_for(f"flag:{index}"),
                student_id=student.id,
                flag_type=(
                    AttentionFlagType.ENGAGEMENT_DECLINE
                    if index % 2
                    else AttentionFlagType.SUDDEN_CHANGE
                ),
                description="Shorter sessions than usual over the past fortnight.",
                # The response model types this as a list of numbers. JSONB will
                # take anything; the read refuses it, so a wrong shape here is a
                # 500 on a screen rather than an error at write time.
                evidence_series=[float(20 - i) for i in range(5)],
                action_targets=["check in", "offer another format"],
                generated_at=NOW - timedelta(days=index),
                acknowledged_at=NOW - timedelta(hours=6) if acknowledged else None,
            )
            made += 1
        await self.session.flush()
        self.note("attention flags", made)
        self.note("students carrying a flag", len(subjects))
        self.note("flags acknowledged", sum(1 for i in range(TOTAL_FLAGS) if i % 3 == 0))

    # ------------------------------------------------------ adaptation events

    async def adaptations(
        self,
        school: School,
        students: list[User],
        author: User,
    ) -> None:
        """Two hundred and fifty events inside seven days.

        This is the threshold that matters most. The adaptation log caps limit
        at 100, and the SENCo screen pages until it sees a short page. On a
        small tenant the first page is always short, so the multi-page path
        has never run. Two hundred and fifty forces three pages.
        """

        lesson = await self.upsert(
            Lesson,
            self.id_for("lesson"),
            school_id=school.id,
            created_by_user_id=author.id,
            title="Simple Interest",
            source_type=LessonSourceType.WORD,
            source_reference={"fileName": "simple-interest-jss3.docx"},
            parser_version=1,
            segment_count=9,
            review_segment_count=1,
        )
        await self.session.flush()

        subjects = [s for s in students if s.status is UserStatus.ACTIVE][:ADAPTATION_STUDENTS]
        sessions = []
        for index, student in enumerate(subjects):
            item = await self.upsert(
                LessonSession,
                self.id_for(f"session:{index}"),
                student_id=student.id,
                lesson_id=lesson.id,
                session_type="lesson",
                started_at=NOW - timedelta(days=index % ADAPTATION_WINDOW_DAYS, hours=2),
                ended_at=NOW - timedelta(days=index % ADAPTATION_WINDOW_DAYS, hours=1),
                completion_status=(
                    LessonCompletionStatus.COMPLETED if index % 3 else LessonCompletionStatus.EXITED
                ),
                exit_position="segment-4",
            )
            sessions.append((student, item))
        await self.session.flush()

        for index in range(ADAPTATION_EVENTS):
            student, session = sessions[index % len(sessions)]
            # Spread across the whole window rather than one timestamp, so
            # ordering and the day buckets are exercised too.
            offset = timedelta(
                days=index % ADAPTATION_WINDOW_DAYS,
                minutes=self.random.randint(0, 600),
            )
            await self.insert_if_missing(
                SignalEvent,
                self.id_for(f"adaptation:{index}"),
                student_id=student.id,
                session_id=session.id,
                event_type=ADAPTATION_TYPES[index % len(ADAPTATION_TYPES)],
                event_data={"triggerReason": "shorter_answers", "segmentId": "segment-4"},
                timestamp=NOW - offset,
            )
        # Replays earn a learner the "revisited content" observation, whose
        # count is null - the case where absent must not render as zero.
        for index in range(4):
            student, session = sessions[0]
            await self.insert_if_missing(
                SignalEvent,
                self.id_for(f"replay:{index}"),
                student_id=student.id,
                session_id=session.id,
                event_type=SignalEventType.REPLAY,
                event_data={"segmentId": "segment-2"},
                timestamp=NOW - timedelta(days=1, minutes=index * 5),
            )
        await self.session.flush()
        self.note("adaptation events (7 days)", ADAPTATION_EVENTS)
        self.note("students with adaptations", len(sessions))
        self.note("lesson sessions", len(sessions))

    # ------------------------------------------------------------------- sso

    async def sso(self, school: School, teachers: list[User]) -> None:
        """A connection with a history that includes a bad run.

        The "View technical details" panel only appears when a run carries
        issues or a failure reason, and the IT Admin Home's "accounts couldn't
        be matched" row needs a run with missing mappings. A clean history
        renders neither, so neither has ever been seen.
        """

        await self.upsert(
            SchoolSsoConfiguration,
            self.id_for("sso"),
            school_id=school.id,
            provider=SsoProvider.MICROSOFT,
            tenant_id="e2e-tenant",
            client_id="e2e-client",
            school_url_slug=school.school_url_slug,
            enabled=True,
            connection_status=SsoConnectionStatus.CONNECTED,
            connection_checked_at=NOW - timedelta(hours=1),
            next_scheduled_sync_at=NOW + timedelta(hours=23),
        )
        runs = [
            ("completed", RosterSyncStatus.COMPLETED, 38, 4, 0, None),
            ("partial", RosterSyncStatus.PARTIAL_MANUAL_REVIEW, 30, 3, 2, None),
            ("failed", RosterSyncStatus.FAILED, 0, 0, 0, "The provider rejected the token."),
            ("recent", RosterSyncStatus.COMPLETED, 40, 4, 0, None),
        ]
        for index, (slug, status, students_in, teachers_in, missing, failure) in enumerate(runs):
            run = await self.upsert(
                RosterSyncRun,
                self.id_for(f"sync:{slug}"),
                school_id=school.id,
                provider=SsoProvider.MICROSOFT,
                status=status,
                imported_students=students_in,
                imported_teachers=teachers_in,
                missing_teacher_class_mappings=missing,
                failure_reason=failure,
                triggered_manually=index == 2,
                triggered_by_user_id=teachers[0].id if index == 2 else None,
                started_at=NOW - timedelta(days=len(runs) - index, minutes=10),
                completed_at=NOW - timedelta(days=len(runs) - index),
            )
            await self.session.flush()
            if missing or failure:
                for issue_index in range(max(missing, 1)):
                    await self.upsert(
                        RosterSyncIssue,
                        self.id_for(f"sync-issue:{slug}:{issue_index}"),
                        roster_sync_run_id=run.id,
                        school_id=school.id,
                        external_reference=f"provider-class-{issue_index + 1}",
                        description="No Nevo class matches this provider class.",
                        resolution_hint="Map it to a class, or ignore it.",
                        status="open",
                    )
        await self.session.flush()
        self.note("sso sync runs", len(runs))
        self.note("sync runs with issues", 2)

    # --------------------------------------------------------------- billing

    async def billing(self, school: School, actor: User) -> None:
        """One paid invoice, one outstanding, a card, and contract dates."""

        start = date(NOW.year, 9, 1)
        # Pricing is per student now, but contracts.tier_id is still NOT NULL,
        # so the row has to point at one. Looked up rather than hardcoded:
        # tier ids differ between environments.
        tier_id = await self.session.scalar(
            select(BillingSubscriptionTier.tier_id).order_by(BillingSubscriptionTier.min_pupils)
        )
        if tier_id is None:
            raise SystemExit(
                "No subscription tiers exist in this database, so a contract "
                "cannot be created. Run the billing migrations first."
            )
        await self.upsert(
            Contract,
            self.id_for("contract"),
            school_id=school.id,
            tier_id=tier_id,
            status=ContractStatus.ACTIVE,
            is_founding_partner=False,
            payment_source=PaymentSource.DIRECT,
            start_date=start,
            end_date=start.replace(year=start.year + 1),
            current_year_index=1,
        )
        await self.upsert(
            BillingPaymentMethod,
            self.id_for("payment-method"),
            school_id=school.id,
            method_type="card",
            processor_name="paystack",
            processor_payment_method_ref="pm_e2e_0001",
            display_name="Visa ending 4242",
            last_four="4242",
            card_brand="visa",
            expiry_month=11,
            expiry_year=NOW.year + 2,
            is_reusable=True,
            updated_by_user_id=actor.id,
        )
        students = CONSENT_MIX[ConsentStatus.CONFIRMED]
        rate = Decimal("150000.00")
        before_vat = rate * students
        vat_rate = Decimal("7.50")
        vat = (before_vat * vat_rate / Decimal("100")).quantize(Decimal("0.01"))
        invoices = [
            ("paid", InvoiceStatus.PAID, NOW - timedelta(days=40), NOW - timedelta(days=30)),
            ("pending", InvoiceStatus.PENDING, NOW - timedelta(days=5), None),
        ]
        for slug, status, issued, paid in invoices:
            number = f"NEVO-{self.school_code[-3:]}-{slug.upper()}"
            await self.upsert(
                Invoice,
                self.id_for(f"invoice:{slug}"),
                school_id=school.id,
                invoice_number=number,
                issued_at=issued.date(),
                amount=before_vat + vat,
                status=status,
                due_at=(issued + timedelta(days=30)).date(),
                paid_at=paid,
                pdf_url=f"/api/billing/invoices/{school.id}/{number}.pdf",
                currency=PricingCurrency.NGN,
                student_count=students,
                per_student_rate=rate,
                total_before_vat=before_vat,
                vat_amount=vat,
                vat_rate=vat_rate,
                period_label=f"{start.year}/{start.year + 1} session",
            )
        await self.session.flush()
        self.note("invoices", len(invoices))
        self.note("payment methods", 1)


async def seed(
    school_code: str,
    *,
    allow_existing: bool,
    dry_run: bool = False,
) -> dict[str, int]:
    engine = create_engine(get_settings().database_url)
    sessions = create_session_factory(engine)
    hasher = build_credential_hasher(AuthSettings())
    try:
        async with sessions() as session, session.begin() as transaction:
            seeder = Seeder(session, school_code=school_code, hasher=hasher)
            existing = await session.scalar(select(School).where(School.school_code == school_code))
            if existing is not None and existing.id != seeder.id_for("school"):
                if not allow_existing:
                    raise SystemExit(
                        f"A school with code {school_code} already exists and was not "
                        "created by this script. Re-run with --allow-existing if you "
                        "really mean to seed into it."
                    )
            school = await seeder.school()
            teachers = await seeder.teachers(school)
            classes = await seeder.classes(school, teachers)
            admin = await seeder.admin(school)
            students = await seeder.students(school, classes, admin)
            await seeder.learner_profiles(students)
            await seeder.flags(students)
            await seeder.rights_requests(students, school)
            await seeder.adaptations(school, students, teachers[0])
            await seeder.sso(school, teachers)
            await seeder.billing(school, admin)
            if dry_run:
                # Everything above ran against the real schema and is about to
                # be thrown away. This is how the script is checked without
                # putting four hundred rows into a live tenant.
                await transaction.rollback()
                seeder.note("ROLLED BACK (dry run)", 1)
            return seeder.summary
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--school-code",
        default="NEVO-E2E",
        help="The tenant to fill. Ids are derived from it, so re-running updates in place.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do all the work, then roll it back. Proves the script runs against the "
        "real schema without writing to the tenant.",
    )
    parser.add_argument(
        "--allow-existing",
        action="store_true",
        help="Seed into a school this script did not create. Off by default.",
    )
    arguments = parser.parse_args()
    summary = asyncio.run(
        seed(
            arguments.school_code,
            allow_existing=arguments.allow_existing,
            dry_run=arguments.dry_run,
        )
    )
    width = max(len(key) for key in summary)
    print(f"\nSeeded {arguments.school_code}:\n")
    for key, value in summary.items():
        print(f"  {key.ljust(width)}  {value}")
    print()


if __name__ == "__main__":
    main()
