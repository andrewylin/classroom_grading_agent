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

    entry_count_match = re.search(r"(\d+)\s+entries?", text, re.IGNORECASE)
    entry_count = int(entry_count_match.group(1)) if entry_count_match else 10
    quote_deduction = 5 if re.search(r"-\s*5|\-5|5\s*points?\s*for.*quote.*context|not integrated with context", text, re.IGNORECASE) else 0
    missing_entry_deduction = 4 if re.search(r"-\s*4|\-4|4\s*points?\s*for\s+each\s+missing\s+entry|missing\s+entry", text, re.IGNORECASE) else 0
    missing_question_set_deduction = 1 if re.search(r"-\s*1|\-1|1\s*point.*each\s+missing.*set|missing.*set.*questions", text, re.IGNORECASE) else 0
    depth_cap_low = 35 if re.search(r"35/50|35\s*/\s*50|35/50.*most.*depth|most entries.*depth", text, re.IGNORECASE) else None
    depth_cap_mid = 40 if re.search(r"40/50|40\s*/\s*50|few entries.*depth|only.*few.*depth", text, re.IGNORECASE) else None

    criteria = [
        RubricCriterion(
            id="required_elements",
            title="Required entries and completeness",
            description=(
                f"Check whether the response contains the required {entry_count} entries. "
                f"Deduct {missing_entry_deduction} points for each missing entry. "
                f"Deduct {quote_deduction} points when a quote is not integrated with context. "
                f"Every quote should be followed by a citation."
            ),
            levels=[
                RubricLevel(score=0, title="Missing major elements", description="Several required entries are absent, uncontextualized, or uncited."),
                RubricLevel(score=score_parts[0] // 2, title="Partially complete", description="Most required content is there, but multiple elements are missing or weak."),
                RubricLevel(score=score_parts[0] * 3 // 4, title="Mostly complete", description="Minor gaps remain, but the required structure is mostly present."),
                RubricLevel(score=score_parts[0], title="Complete", description="All required entries are present and properly contextualized."),
            ],
        ),
        RubricCriterion(
            id="quote_integration",
            title="Quote integration and citations",
            description=(
                "Evaluate whether each quote is woven into the response with context and explanation. "
                "If a quote is dropped in without setting up the idea or without a citation, score down. "
                "The strongest responses connect quotes to a clear claim, analysis, or reflection."
            ),
            levels=[
                RubricLevel(score=0, title="Weak integration", description="Quotes are inserted without context, explanation, or citation."),
                RubricLevel(score=score_parts[1] // 2, title="Mixed integration", description="Some quotes are integrated, but several are unsupported or under-explained."),
                RubricLevel(score=score_parts[1] * 3 // 4, title="Generally integrated", description="Most quotes are contextualized and cited."),
                RubricLevel(score=score_parts[1], title="Strong integration", description="Quotes are clearly contextualized, analyzed, and cited."),
            ],
        ),
        RubricCriterion(
            id="discussion_questions",
            title="Discussion questions",
            description=(
                "There should be 5 sets of 3 discussion questions. "
                f"Deduct {missing_question_set_deduction} points for each missing set of questions. "
                "A full set should be complete, relevant, and connected to the text."
            ),
            levels=[
                RubricLevel(score=0, title="Missing sets", description="Several question sets are absent or incomplete."),
                RubricLevel(score=score_parts[2] // 2, title="Partial sets", description="Some question sets are present but incomplete or shallow."),
                RubricLevel(score=score_parts[2] * 3 // 4, title="Mostly complete", description="Most question sets are included and relevant."),
                RubricLevel(score=score_parts[2], title="Complete", description="All required discussion-question sets are present and useful."),
            ],
        ),
        RubricCriterion(
            id="depth_and_analysis",
            title="Depth and analytical quality",
            description=(
                "Reward thoughtful, evidence-based analysis rather than summary alone. "
                f"If most entries lack depth, the submission should not score above {depth_cap_low or 'the cap'} on the full assignment. "
                f"If only a few entries lack depth, a score around {depth_cap_mid or 'the middle cap'} is more appropriate. "
                "High-performing work connects quotes to broader ideas, literary analysis, outside reading, or reflective questions."
            ),
            levels=[
                RubricLevel(score=0, title="Very shallow", description="Most entries are thin, summary-based, or unsupported."),
                RubricLevel(score=score_parts[3] // 2, title="Some depth", description="A few entries show analysis, but the overall response is still limited."),
                RubricLevel(score=score_parts[3] * 3 // 4, title="Moderately deep", description="Several entries show real analysis and reflection."),
                RubricLevel(score=score_parts[3], title="Strong depth", description="The response is consistently analytical, reflective, and evidence-based."),
            ],
        ),
    ]
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
