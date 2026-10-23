"""Repair only invalid question fields; retain the original lesson and prompts."""

import json
from copy import deepcopy

from nevo.ai_gateway.entities import AiGenerationRequest
from nevo.api.lesson_contracts import UnclassifiableQuestionError, checkpoint_payloads
from nevo.domain.ai_gateway.vocabulary import AiService

PROMPT_NAME = "content_question_repair.default"


async def repair_questions(payload, *, source, gateway, requester_user_id):
    fixed = deepcopy(payload)
    containers = []
    for section in fixed.get("segments", []):
        if not isinstance(section, dict):
            raise UnclassifiableQuestionError("Unclassifiable question container")
        containers.append(
            section.get("comprehension_checkpoints") or section.get("comprehensionCheckpoints")
        )
    containers.append(fixed.get("assessment"))
    broken = {}
    for questions in containers:
        if questions is None:
            continue
        if not isinstance(questions, list):
            raise UnclassifiableQuestionError("Unclassifiable question container")
        for question in questions:
            if not isinstance(question, dict):
                raise UnclassifiableQuestionError("Unclassifiable question item")
            try:
                checkpoint_payloads([question], segment_key="repair", strict=True)
            except (UnclassifiableQuestionError, TypeError, ValueError):
                if not str(question.get("prompt") or "").strip():
                    raise UnclassifiableQuestionError(
                        "Unclassifiable question: missing prompt"
                    ) from None
                broken[f"repair-{len(broken) + 1}"] = question
    if not broken:
        raise UnclassifiableQuestionError("Unclassifiable question outside supported repair")
    last_error = None
    for attempt in range(3):
        response = await gateway.generate(
            AiGenerationRequest(
                requester_user_id=requester_user_id,
                service=AiService.LESSON_GENERATION,
                prompt_name=PROMPT_NAME,
                variables={
                    "source_text": source,
                    "questions": json.dumps(
                        [
                            {
                                "repairId": key,
                                "question": question,
                                "previousValidationError": str(last_error)[:500]
                                if last_error
                                else None,
                            }
                            for key, question in broken.items()
                        ]
                    ),
                },
                json_output=True,
                max_output_tokens=min(8192, max(2048, len(broken) * 1024)),
                timeout_seconds=90,
            )
        )
        try:
            from nevo.content_parsing.service import _json_payload

            if response.fallback_used:
                raise ValueError(
                    "Question correction requires a real source-grounded model response"
                )
            decoded = _json_payload(response.text)
            rows = decoded["questions"]
            if not isinstance(rows, list) or len(rows) != len(broken):
                raise ValueError("Question correction omitted a repair")
            repaired = {}
            seen = set()
            for row in rows:
                identity = row.get("repairId")
                if identity not in broken or identity in seen:
                    raise ValueError("Question correction returned an invalid repair identifier")
                seen.add(identity)
                corrected = dict(broken[identity])
                for field in ("answerType", "answerKey", "options", "acceptedAnswers"):
                    if field in row:
                        corrected[field] = row[field]
                checkpoint_payloads([corrected], segment_key="repair", strict=True)
                repaired[identity] = corrected
            for identity, corrected in repaired.items():
                # No model-provided prompt, id, hint, section or prose is copied back.
                broken[identity].clear()
                broken[identity].update(corrected)
            return fixed
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            last_error = error
    raise UnclassifiableQuestionError(
        "Unclassifiable question after three targeted corrections"
    ) from last_error
