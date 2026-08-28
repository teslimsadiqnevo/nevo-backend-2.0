from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.db.models.account import Class, StudentClassEnrollment, User
from nevo.db.models.frontend_support import Concept
from nevo.db.models.mastery import StudentConceptMastery
from nevo.domain.accounts.vocabulary import UserStatus
from nevo.mastery.engine import concept_seed_from_theta, reading_seed_from_wpm
from nevo.mastery.entities import (
    BaselineMasterySeed,
    ConceptMasteryAggregate,
    MasteryState,
)


class SqlAlchemyMasteryRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def state(
        self,
        *,
        student_id: UUID,
        concept_id: UUID,
    ) -> MasteryState | None:
        async with self._sessions() as session:
            record = await session.scalar(
                select(StudentConceptMastery).where(
                    StudentConceptMastery.student_id == student_id,
                    StudentConceptMastery.concept_id == concept_id,
                )
            )
        if record is None:
            return None
        return _state_from_record(record, concept_name=None)

    async def baseline_seed(self, student_id: UUID) -> BaselineMasterySeed:
        async with self._sessions() as session:
            user = await session.scalar(
                select(User).where(
                    User.id == student_id,
                    User.status != UserStatus.DEACTIVATED,
                )
            )
            payload = getattr(user, "baseline_profile", None)
        if isinstance(payload, dict):
            theta_domain = _float_or_none(payload.get("theta_domain"))
            reading_wpm = _float_or_none(payload.get("reading_wpm"))
            age_band = payload.get("age_band")
            return BaselineMasterySeed(
                concept_probability=concept_seed_from_theta(theta_domain),
                reading_probability=reading_seed_from_wpm(
                    reading_wpm,
                    age_band=str(age_band) if age_band else None,
                ),
                source="baseline_profile",
            )
        return BaselineMasterySeed(
            concept_probability=concept_seed_from_theta(None),
            reading_probability=reading_seed_from_wpm(None, age_band=None),
            source="default_until_scrum_104",
        )

    async def related_mastery(
        self,
        *,
        student_id: UUID,
        concept_ids: tuple[UUID, ...],
    ) -> dict[UUID, float]:
        if not concept_ids:
            return {}
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(
                        StudentConceptMastery.concept_id,
                        StudentConceptMastery.mastery_probability_concept,
                    ).where(
                        StudentConceptMastery.student_id == student_id,
                        StudentConceptMastery.concept_id.in_(concept_ids),
                    )
                )
            ).all()
        return dict(rows)

    async def save(self, state: MasteryState) -> MasteryState:
        async with self._sessions.begin() as session:
            record = await session.scalar(
                select(StudentConceptMastery).where(
                    StudentConceptMastery.student_id == state.student_id,
                    StudentConceptMastery.concept_id == state.concept_id,
                )
            )
            values = {
                "mastery_probability_concept": state.mastery_probability_concept,
                "mastery_probability_reading": state.mastery_probability_reading,
                "attention_weights": state.attention_weights,
                "guess_probability": state.guess_probability,
                "slip_probability": state.slip_probability,
                "practice_count": state.practice_count,
                "last_response_correct": state.last_response_correct,
                "last_failure_attribution": state.last_failure_attribution,
                "seeding_source": state.seeding_source,
                "last_updated": func.now(),
            }
            if record is None:
                record = StudentConceptMastery(
                    student_id=state.student_id,
                    concept_id=state.concept_id,
                    **values,
                )
                session.add(record)
                await session.flush()
            else:
                await session.execute(
                    update(StudentConceptMastery)
                    .where(StudentConceptMastery.id == record.id)
                    .values(**values)
                )
                await session.refresh(record)
        return state

    async def student_mastery(self, student_id: UUID) -> tuple[MasteryState, ...]:
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(StudentConceptMastery)
                    .where(StudentConceptMastery.student_id == student_id)
                    .order_by(StudentConceptMastery.concept_id)
                )
            ).all()
        concept_names = await self._concept_names(tuple(row.concept_id for row in rows))
        return tuple(
            _state_from_record(row, concept_name=concept_names.get(row.concept_id))
            for row in rows
        )

    async def class_mastery(
        self,
        class_id: UUID,
    ) -> tuple[ConceptMasteryAggregate, ...]:
        async with self._sessions() as session:
            school_class = await session.get(Class, class_id)
            if school_class is None:
                return ()
            rows = (
                await session.execute(
                    select(
                        StudentConceptMastery.concept_id,
                        Concept.name,
                        func.count(StudentConceptMastery.student_id),
                        func.avg(
                            StudentConceptMastery.mastery_probability_concept
                        ),
                        func.avg(
                            StudentConceptMastery.mastery_probability_reading
                        ),
                    )
                    .outerjoin(Concept, Concept.id == StudentConceptMastery.concept_id)
                    .join(
                        StudentClassEnrollment,
                        StudentClassEnrollment.student_id
                        == StudentConceptMastery.student_id,
                    )
                    .where(StudentClassEnrollment.class_id == class_id)
                    .group_by(StudentConceptMastery.concept_id, Concept.name)
                    .order_by(Concept.name, StudentConceptMastery.concept_id)
                )
            ).all()
        return tuple(_aggregate_from_row(row) for row in rows)

    async def school_mastery(
        self,
        school_id: UUID,
    ) -> tuple[ConceptMasteryAggregate, ...]:
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(
                        StudentConceptMastery.concept_id,
                        Concept.name,
                        func.count(StudentConceptMastery.student_id),
                        func.avg(
                            StudentConceptMastery.mastery_probability_concept
                        ),
                        func.avg(
                            StudentConceptMastery.mastery_probability_reading
                        ),
                    )
                    .outerjoin(Concept, Concept.id == StudentConceptMastery.concept_id)
                    .join(User, User.id == StudentConceptMastery.student_id)
                    .where(User.school_id == school_id)
                    .group_by(StudentConceptMastery.concept_id, Concept.name)
                    .order_by(Concept.name, StudentConceptMastery.concept_id)
                )
            ).all()
        return tuple(_aggregate_from_row(row) for row in rows)


    async def _concept_names(self, concept_ids: tuple[UUID, ...]) -> dict[UUID, str]:
        if not concept_ids:
            return {}
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(Concept.id, Concept.name).where(Concept.id.in_(concept_ids))
                )
            ).all()
        return dict(rows)


def _state_from_record(
    record: StudentConceptMastery,
    *,
    concept_name: str | None,
) -> MasteryState:
    return MasteryState(
        student_id=record.student_id,
        concept_id=record.concept_id,
        concept_name=concept_name or _fallback_concept_name(record.concept_id),
        mastery_probability_concept=record.mastery_probability_concept,
        mastery_probability_reading=record.mastery_probability_reading,
        attention_weights=dict(record.attention_weights),
        guess_probability=record.guess_probability,
        slip_probability=record.slip_probability,
        practice_count=record.practice_count,
        last_response_correct=record.last_response_correct,
        last_failure_attribution=record.last_failure_attribution,
        seeding_source=record.seeding_source,
    )


def _aggregate_from_row(
    row: tuple[UUID, str | None, int, float, float],
) -> ConceptMasteryAggregate:
    concept_id, concept_name, student_count, concept_avg, reading_avg = row
    return ConceptMasteryAggregate(
        concept_id=concept_id,
        concept_name=concept_name or _fallback_concept_name(concept_id),
        student_count=student_count,
        mastery_probability_concept=round(float(concept_avg or 0), 6),
        mastery_probability_reading=round(float(reading_avg or 0), 6),
    )


def _fallback_concept_name(concept_id: UUID) -> str:
    return f"Concept {str(concept_id)[:8]}"


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
