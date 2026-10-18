from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5


@dataclass(frozen=True)
class DeliveryModule:
    id: object
    title: str
    sequence_order: int
    segment_ids: list[str]
    recap: str | None = None
    preview: str | None = None


def delivery_modules(lesson_id, segments, modules):
    """Legacy lessons get the same complete module contract without data mutation."""
    available = {value for segment in segments for value in (str(segment.id), segment.segment_key)}
    used = [str(value) for module in modules for value in module.segment_ids]
    if modules and len(used) == len(set(used)) and all(value in available for value in used):
        covered = {
            segment.id
            for segment in segments
            if str(segment.id) in used or segment.segment_key in used
        }
        if len(covered) == len(segments):
            return modules
    if len(segments) < 6:
        return []
    return [
        DeliveryModule(
            id=uuid5(NAMESPACE_URL, f"nevo:{lesson_id}:module:{segments[index].segment_key}"),
            title=segments[index].title or "Exploring this idea",
            sequence_order=index // 3 + 1,
            segment_ids=[segment.segment_key for segment in segments[index : index + 3]],
        )
        for index in range(0, len(segments), 3)
    ]
