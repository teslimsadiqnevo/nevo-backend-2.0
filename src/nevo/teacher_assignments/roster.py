from uuid import UUID

from nevo.teacher_assignments.entities import RosterAssignmentBatch


class UnavailableRosterAssignmentProvider:
    async def assignments_for_school(
        self,
        school_id: UUID,
    ) -> RosterAssignmentBatch:
        del school_id
        return RosterAssignmentBatch(supported=False)
