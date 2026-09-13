"""Talks to the local Ollama server to grade one essay against one rubric."""
import json
import requests

import config
from models import Rubric, CriterionScore, GradeResult


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
        "Here are examples of how this teacher has graded THIS EXACT assignment "
        "before. Match this grading style, rigor, and standards exactly - these "
        "are ground truth, not suggestions.\n"
    ]
    for i, ex in enumerate(calibration_examples, 1):
        blocks.append(f"--- Calibration example {i} ---")
        blocks.append(f"Essay:\n\"\"\"\n{ex['essay_text']}\n\"\"\"")
        blocks.append("Teacher's scores:")
        for c in rubric.criteria:
            cs = ex["criterion_scores"].get(c.id)
            if cs:
                blocks.append(f"  {c.title}: {cs['score']}/{c.max_score} — {cs['justification']}")
        blocks.append(f"Teacher's feedback: {ex['feedback_summary']}\n")
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

    return f"""You are grading a high school student's writing assignment.

Assignment: {assignment_title}
Assignment instructions: {assignment_instructions}

Rubric:
{rubric_block}

{calibration_block}
Now grade the following NEW student's essay the same way, matching the
calibration examples' style and rigor if any were given above.

Student essay:
\"\"\"
{essay_text}
\"\"\"

Score every rubric criterion independently, using only the point values defined
for that criterion. For each criterion give a 1-2 sentence justification tied to
specific evidence in the essay. Then write a short (3-5 sentence) overall
feedback summary aimed at the student: what's working, and the single most
useful thing to revise next. Be specific — cite the essay's own content, not
generic advice. Do not be swayed by essay length or vocabulary alone; grade
against the rubric language."""


def grade_essay(
    rubric: Rubric,
    assignment_title: str,
    assignment_instructions: str,
    essay_text: str,
    calibration_examples: list[dict] | None = None,
) -> GradeResult:
    schema = _build_schema(rubric)
    prompt = _build_prompt(rubric, assignment_title, assignment_instructions, essay_text, calibration_examples)

    payload = {
        "model": config.MODEL_NAME,
        "messages": [{"role": "user", "content": prompt}],
        "format": schema,
        "stream": False,
        "think": config.MODEL_THINKING,  # Qwen3 hybrid reasoning: reason before scoring
        "options": {"temperature": 0.2},
    }
    resp = requests.post(f"{config.OLLAMA_HOST}/api/chat", json=payload, timeout=config.MODEL_TIMEOUT_SECONDS)
    resp.raise_for_status()
    content = resp.json()["message"]["content"]
    parsed = json.loads(content)

    criterion_scores = []
    total_score = 0.0
    for c in rubric.criteria:
        entry = parsed["criteria"][c.id]
        criterion_scores.append(CriterionScore(
            criterion_id=c.id, criterion_title=c.title,
            score=entry["score"], max_score=c.max_score,
            justification=entry["justification"],
        ))
        total_score += entry["score"]

    return GradeResult(
        submission_id="",  # filled in by the caller
        criterion_scores=criterion_scores,
        overall_score=total_score,
        overall_max=rubric.max_total,
        feedback_summary=parsed["feedback_summary"],
    )
