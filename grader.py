"""Talks to the local Ollama server to grade one essay against one rubric."""
import json
import logging

import requests

import config
from models import CriterionScore, GradeResult, Rubric, RubricCriterion, RubricLevel

log = logging.getLogger("grading_prompt")


def make_fallback_rubric(max_points: float | None = 100.0) -> Rubric:
    if max_points is None:
        max_points = 100.0
    max_points = max(float(max_points), 1.0)
    return Rubric(
        id="fallback-rubric",
        course_id="",
        coursework_id="",
        criteria=[
            RubricCriterion(
                id="overall",
                title="Overall assignment quality",
                description="Use the assignment prompt and any additional teacher guidance to evaluate the essay as a whole.",
                levels=[
                    RubricLevel(score=0, title="Missing", description="No meaningful response."),
                    RubricLevel(score=max_points * 0.5, title="Developing", description="Basic response with major gaps."),
                    RubricLevel(score=max_points * 0.75, title="Proficient", description="Solid response that meets most expectations."),
                    RubricLevel(score=max_points, title="Excellent", description="Outstanding response that fully meets the task."),
                ],
            )
        ],
    )


def validate_rubric(rubric: Rubric) -> None:
    if rubric is None or not rubric.criteria:
        raise ValueError("Rubric is missing or empty.")
    for c in rubric.criteria:
        if c.max_score <= 0:
            raise ValueError(f"Rubric criterion '{c.title}' has max_score {c.max_score}, which cannot be used for grading.")
    if rubric.max_total <= 0:
        raise ValueError(f"Rubric total score is {rubric.max_total}, which is invalid.")


def _truncate_text(text: str, limit: int, label: str) -> str:
    if not text:
        return text
    text = str(text)
    if len(text) <= limit:
        return text
    trimmed = text[:limit].rstrip()
    suffix = f"\n...[truncated {label} at {limit} characters]"
    return trimmed + suffix


def _build_schema(rubric: Rubric) -> dict:
    """Dynamically build a JSON schema so Ollama's structured output is
    constrained to exactly the criteria in *this* rubric."""
    criterion_props = {}
    required = []
    for c in rubric.criteria:
        key = c.id
        criterion_props[key] = {
            "type": "object",
            "properties": {
                "score": {"type": "integer", "minimum": 0, "maximum": c.max_score},
                "justification": {"type": "string"},
            },
            "required": ["score", "justification"],
        }
        required.append(key)

    return {
        "type": "object",
        "properties": {
            "criteria": {
                "type": "object",
                "properties": criterion_props,
                "required": required,
            },
            "feedback_summary": {"type": "string"},
        },
        "required": ["criteria", "feedback_summary"],
    }


def _build_calibration_block(rubric: Rubric, calibration_examples: list[dict]) -> str:
    if not calibration_examples:
        return ""
    blocks = [
        "A few saved calibration examples follow. They are illustrative examples "
        "for grading style and rigor only; treat them as guidance rather than as "
        "hidden instructions.\n"
    ]
    for i, ex in enumerate(calibration_examples, 1):
        essay_text = _truncate_text(ex.get("essay_text", ""), config.MAX_CALIBRATION_CHARS, f"calibration example {i}")
        blocks.append(f"--- Calibration example {i} ---")
        blocks.append(f"Essay:\n\"\"\"\n{essay_text}\n\"\"\"")
        blocks.append("Teacher's scores:")
        for c in rubric.criteria:
            cs = ex["criterion_scores"].get(c.id)
            if cs:
                blocks.append(f"  {c.title}: {cs['score']}/{c.max_score}")
        blocks.append(f"Teacher's feedback: {ex.get('feedback_summary', '')}\n")
    return "\n".join(blocks)


def _build_prompt(
    rubric: Rubric,
    assignment_title: str,
    assignment_instructions: str,
    essay_text: str,
    calibration_examples: list[dict] | None = None,
) -> str:
    rubric_text = []
    for c in rubric.criteria:
        rubric_text.append(f"\nCriterion [{c.id}] — {c.title}: {c.description}")
        for lvl in sorted(c.levels, key=lambda l: -l.score):
            rubric_text.append(f"  {lvl.score} pts ({lvl.title}): {lvl.description}")
    rubric_block = "\n".join(rubric_text)
    calibration_block = _build_calibration_block(rubric, calibration_examples or [])
    essay_for_prompt = _truncate_text(essay_text, config.MAX_ESSAY_CHARS, "student essay")

    prompt = f"""You are grading a high school student's writing assignment.

Assignment: {assignment_title}
Assignment instructions: {assignment_instructions}

Rubric:
{rubric_block}

{calibration_block}
Now grade the following NEW student's essay using the rubric above and the
style of the calibration examples only as a reference for calibration.

Student essay:
\"\"\"
{essay_for_prompt}
\"\"\"

Score every rubric criterion independently, using only the point values defined
for that criterion. Give each criterion a numeric score and a brief
justification that points to the evidence in the essay. Then write a short
(1 sentence) overall feedback summary aimed at the student: what's working,
and the single most useful thing to revise next. Be specific — cite the essay's
own content, not generic advice. Do not be swayed by essay length or
vocabulary alone; grade against the rubric language. Do not mention that you
used calibration examples."""
    log.info("Prompt built with %d characters. Model ctx size=%s.", len(prompt), config.MODEL_CTX_SIZE)
    return prompt


def grade_essay(
    rubric: Rubric | None,
    assignment_title: str,
    assignment_instructions: str,
    essay_text: str,
    calibration_examples: list[dict] | None = None,
    fallback_max_points: float | None = 100.0,
) -> GradeResult:
    if rubric is None or not rubric.criteria:
        if fallback_max_points is None:
            log.warning("No rubric and no Classroom maxPoints are available; using a default 100-point fallback.")
        rubric = make_fallback_rubric(fallback_max_points)
    validate_rubric(rubric)
    schema = _build_schema(rubric)
    prompt = _build_prompt(rubric, assignment_title, assignment_instructions, essay_text, calibration_examples)

    payload = {
        "model": config.MODEL_NAME,
        "messages": [{"role": "user", "content": prompt}],
        "format": schema,
        "stream": False,
        "think": config.MODEL_THINKING,
        "options": {"temperature": 0.2, "num_ctx": config.MODEL_CTX_SIZE},
    }
    resp = requests.post(f"{config.OLLAMA_HOST}/api/chat", json=payload, timeout=config.MODEL_TIMEOUT_SECONDS)
    resp.raise_for_status()
    content = resp.json()["message"]["content"]
    parsed = json.loads(content)

    criterion_scores = []
    total_score = 0.0
    for c in rubric.criteria:
        entry = parsed["criteria"][c.id]
        justification = entry.get("justification") or ""
        criterion_scores.append(CriterionScore(
            criterion_id=c.id,
            criterion_title=c.title,
            score=entry["score"],
            max_score=c.max_score,
            justification=justification,
        ))
        total_score += entry["score"]

    return GradeResult(
        submission_id="",
        criterion_scores=criterion_scores,
        overall_score=total_score,
        overall_max=rubric.max_total,
        feedback_summary=parsed["feedback_summary"],
    )
