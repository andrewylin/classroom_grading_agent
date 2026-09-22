"""Talks to the local Ollama server to grade one essay against one rubric."""
import json
import logging
import re

import requests

import config
from models import CriterionScore, GradeResult, Rubric, RubricCriterion, RubricLevel

log = logging.getLogger("grading_prompt")


def _score_band_points(max_points: float | None = 100.0) -> list[int]:
    total = max(float(max_points or 100.0), 1.0)
    raw_weights = [0.40, 0.30, 0.20, 0.10]
    scores = [int(round(total * weight)) for weight in raw_weights]
    scores[-1] = int(total - sum(scores[:-1]))
    return scores


def _has_point_deduction_language(text: str) -> bool:
    """Never infer a custom rubric from free-form text. The assignment-specific
    rubric is only allowed through an explicit opt-in path when the teacher has
    confirmed custom grading instructions for the assignment."""
    return False


def should_use_custom_rubric(instructions: str, assignment_description: str, explicit_opt_in: bool = False) -> bool:
    text = (instructions or "").strip()
    if not text:
        return False
    if not explicit_opt_in:
        return False
    return bool(text)


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
                    RubricLevel(score=int(round(max_points * 0.5)), title="Developing", description="Basic response with major gaps."),
                    RubricLevel(score=int(round(max_points * 0.75)), title="Proficient", description="Solid response that meets most expectations."),
                    RubricLevel(score=int(round(max_points)), title="Excellent", description="Outstanding response that fully meets the task."),
                ],
            )
        ],
    )


def build_custom_rubric_from_instructions(instructions: str, max_points: float | None = 100.0) -> Rubric:
    text = (instructions or "").strip()
    total = max(float(max_points or 100.0), 1.0)
    score_parts = _score_band_points(total)

    lowered = text.lower()
    topic_map = {
        "argument": ["thesis", "claim", "argument", "position", "purpose"],
        "evidence": ["evidence", "quote", "source", "citation", "support", "details"],
        "organization": ["organization", "structure", "paragraph", "format", "introduction", "conclusion", "flow"],
        "analysis": ["analysis", "explain", "reasoning", "reflection", "interpretation", "connect"],
        "mechanics": ["grammar", "mechanics", "sentence", "style", "clarity", "conventions"],
    }

    matches = []
    for criterion_id, keywords in topic_map.items():
        if any(keyword in lowered for keyword in keywords):
            matches.append(criterion_id)

    if not matches:
        matches = ["argument", "evidence", "organization"]

    criteria = []
    for index, criterion_id in enumerate(matches[:4]):
        title_map = {
            "argument": "Thesis and argument",
            "evidence": "Evidence and support",
            "organization": "Organization and structure",
            "analysis": "Reasoning and explanation",
            "mechanics": "Clarity and mechanics",
        }
        description_map = {
            "argument": "Evaluate whether the response states a clear position and develops a focused, defensible argument that answers the assignment prompt.",
            "evidence": "Evaluate whether the response uses relevant evidence, examples, quotations, or sources to support the central claim and explain how they matter.",
            "organization": "Evaluate whether the response is logically organized, clearly structured, and easy for a reader to follow from beginning to end.",
            "analysis": "Evaluate whether the response explains ideas, makes connections, and shows reasoning beyond summary or surface description.",
            "mechanics": "Evaluate whether the writing is clear, coherent, and polished enough to communicate ideas effectively.",
        }
        score = score_parts[index % len(score_parts)]
        criteria.append(
            RubricCriterion(
                id=f"criterion_{index + 1}",
                title=title_map[criterion_id],
                description=description_map[criterion_id],
                levels=[
                    RubricLevel(score=0, title="Missing", description="This element is absent or not meaningfully present."),
                    RubricLevel(score=score // 2, title="Developing", description="This element is present but uneven or incomplete."),
                    RubricLevel(score=score * 3 // 4, title="Proficient", description="This element is generally well handled with minor weaknesses."),
                    RubricLevel(score=score, title="Excellent", description="This element is strong, clear, and fully aligned with the assignment."),
                ],
            )
        )

    return Rubric(id="custom-instructions-rubric", course_id="", coursework_id="", criteria=criteria)


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
    explicit_custom_rubric: bool = False,
) -> GradeResult:
    if rubric is None or not rubric.criteria:
        if should_use_custom_rubric(assignment_instructions, assignment_title, explicit_opt_in=explicit_custom_rubric):
            rubric = build_custom_rubric_from_instructions(assignment_instructions, fallback_max_points)
        else:
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
