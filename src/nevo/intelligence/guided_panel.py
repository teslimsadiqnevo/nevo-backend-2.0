"""Mark structured guided steps against stored keys; the original check stays the gate."""

from uuid import NAMESPACE_DNS, uuid5

from fastapi import HTTPException
from sqlalchemy import select

from nevo.content_parsing.answers import answer_matches
from nevo.db.models.product import LessonQuestionAttempt


def guided_question_prompt_id(question_id: str, index: int) -> str:
    stable = uuid5(NAMESPACE_DNS, question_id).hex[:24]
    return f"gq-{stable}-{index}"


def public_prompt(step):
    return {key: step[key] for key in ("id", "prompt", "answerType", "options") if key in step}


async def answer_step(session, sitting, payload):
    query = select(LessonQuestionAttempt).where(
        LessonQuestionAttempt.lesson_id == sitting.lesson_id,
        LessonQuestionAttempt.student_id == sitting.student_id,
        LessonQuestionAttempt.source != "assessment",
    )
    if payload.question_id:
        query = query.where(LessonQuestionAttempt.question_id == payload.question_id)
    attempts = list(
        await session.scalars(query.order_by(LessonQuestionAttempt.submitted_at.desc()))
    )
    source = next(
        (
            row
            for row in attempts
            if any(
                payload.prompt_id == guided_question_prompt_id(row.question_id, index)
                for index, question in enumerate(
                    row.question_snapshot.get("guidedQuestions") or [], start=1
                )
                if isinstance(question, str) and question.strip()
            )
        ),
        None,
    )
    if source is not None:
        questions = [
            question.strip()
            for question in (source.question_snapshot.get("guidedQuestions") or [])
            if isinstance(question, str) and question.strip()
        ]
        prompts = [
            {
                "id": guided_question_prompt_id(source.question_id, index),
                "prompt": question,
                "answerType": "text",
                "options": [],
            }
            for index, question in enumerate(questions, start=1)
        ]
        index = next(i for i, prompt in enumerate(prompts) if prompt["id"] == payload.prompt_id)
        delivery = dict(sitting.delivery_state or {})
        panels = dict(delivery.get("guidedQuestionProgress") or {})
        progress = dict(panels.get(source.question_id) or {})
        answered = int(progress.get("answered", 0))
        if index != answered:
            raise HTTPException(
                409,
                detail={
                    "code": "guided_step_out_of_order",
                    "prompt": prompts[min(answered, len(prompts) - 1)],
                },
            )
        if payload.response_length is None:
            raise HTTPException(
                422,
                detail={
                    "code": "guided_response_length_required",
                    "message": "Send responseLength only; the child's written response stays on device.",
                },
            )
        answered += 1
        progress["answered"] = answered
        panels[source.question_id] = progress
        sitting.delivery_state = {**delivery, "guidedQuestionProgress": panels}
        next_prompt = prompts[answered] if answered < len(prompts) else None
        return {
            "recorded": True,
            "promptId": payload.prompt_id,
            "correct": None,
            "panelComplete": next_prompt is None,
            "canAdvance": False,
            "retryCheck": next_prompt is None,
            "questionId": source.question_id,
            "prompt": next_prompt,
            "feedback": None,
        }
    matches = [
        row
        for row in attempts
        if any(
            step.get("id") == payload.prompt_id
            for step in row.question_snapshot.get("guidedSteps", [])
        )
    ]
    if not payload.question_id and len({row.question_id for row in matches}) > 1:
        raise HTTPException(409, detail={"code": "guided_question_required"})
    source = matches[0] if matches else None
    if source is None:
        raise HTTPException(404, detail={"code": "guided_prompt_not_found"})
    steps = source.question_snapshot["guidedSteps"]
    delivery = dict(sitting.delivery_state or {})
    panels = dict(delivery.get("guidedProgress") or {})
    progress = dict(panels.get(source.question_id) or {})
    passed = set(progress.get("passed", []))
    current = next((step for step in steps if step["id"] not in passed), None)
    if current is None:
        return {
            "recorded": True,
            "promptId": payload.prompt_id,
            "correct": None,
            "panelComplete": True,
            "canAdvance": False,
            "retryCheck": True,
            "questionId": source.question_id,
        }
    if current["id"] != payload.prompt_id:
        raise HTTPException(
            409, detail={"code": "guided_step_out_of_order", "prompt": public_prompt(current)}
        )
    answer = payload.answer if payload.answer is not None else payload.option
    if answer is None:
        raise HTTPException(
            422,
            detail={
                "code": "guided_answer_required",
                "message": "Choose or construct an answer. Response length is not an answer.",
            },
        )
    correct = answer_matches(answer, current) is True
    if correct:
        passed.add(current["id"])
    next_step = next((step for step in steps if step["id"] not in passed), None)
    progress["passed"] = [step["id"] for step in steps if step["id"] in passed]
    progress["attempts"] = int(progress.get("attempts", 0)) + 1
    panels[source.question_id] = progress
    hinted = list(dict.fromkeys([*delivery.get("hintedQuestions", []), source.question_id]))
    sitting.delivery_state = {**delivery, "guidedProgress": panels, "hintedQuestions": hinted}
    return {
        "recorded": True,
        "promptId": current["id"],
        "correct": correct,
        "panelComplete": next_step is None,
        "canAdvance": False,
        "retryCheck": next_step is None,
        "questionId": source.question_id,
        "prompt": public_prompt(next_step) if next_step else None,
        "feedback": current.get("explanation") if not correct else None,
    }
