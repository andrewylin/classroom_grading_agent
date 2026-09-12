"""Core data structures shared across the grading pipeline."""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RubricLevel:
    score: int
    title: str
    description: str


@dataclass
class RubricCriterion:
    id: str
    title: str
    description: str
    levels: list[RubricLevel]

    @property
    def max_score(self) -> int:
        return max((lvl.score for lvl in self.levels), default=0)


@dataclass
class Rubric:
    id: str
    course_id: str
    coursework_id: str
    criteria: list[RubricCriterion]

    @property
    def max_total(self) -> int:
        return sum(c.max_score for c in self.criteria)


@dataclass
class Submission:
    submission_id: str
    course_id: str
    coursework_id: str
    student_user_id: str
    drive_file_id: str
    state: str
    doc_revision_id: Optional[str] = None


@dataclass
class CriterionScore:
    criterion_id: str
    criterion_title: str
    score: int
    max_score: int
    justification: str


@dataclass
class GradeResult:
    submission_id: str
    criterion_scores: list[CriterionScore]
    overall_score: float
    overall_max: float
    feedback_summary: str

    def as_comment_text(self) -> str:
        """Render the grade result as a single Drive comment."""
        lines = [f"AI-assisted grade: {self.overall_score:.1f} / {self.overall_max:.0f}", ""]
        for cs in self.criterion_scores:
            lines.append(f"• {cs.criterion_title}: {cs.score}/{cs.max_score} — {cs.justification}")
        lines.append("")
        lines.append(self.feedback_summary)
        lines.append("")
        lines.append("(Draft grade posted to Classroom — review before returning.)")
        return "\n".join(lines)
