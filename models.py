"""Core data structures shared across the grading pipeline."""
from dataclasses import dataclass
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
    justification: str | None = None


@dataclass
class GradeResult:
    submission_id: str
    criterion_scores: list[CriterionScore]
    overall_score: float
    overall_max: float
    feedback_summary: str


@dataclass
class Recommendation:
    """A grading recommendation plus the context needed to act on it manually
    - this is what actually gets written to the output report. Nothing here
    is ever pushed back to Classroom or Drive."""
    course_id: str
    coursework_id: str
    coursework_title: str
    submission_id: str
    student_user_id: str
    student_name: str
    doc_revision_id: str
    grade: GradeResult

    def to_row(self) -> dict:
        return {
            "course_id": self.course_id,
            "coursework_id": self.coursework_id,
            "coursework_title": self.coursework_title,
            "student_name": self.student_name,
            "student_user_id": self.student_user_id,
            "submission_id": self.submission_id,
            "recommended_grade": f"{self.grade.overall_score:.1f}",
            "max_grade": f"{self.grade.overall_max:.0f}",
            "criteria_breakdown": " | ".join(
                f"{cs.criterion_title}: {cs.score}/{cs.max_score}"
                for cs in self.grade.criterion_scores
            ),
            "feedback_summary": self.grade.feedback_summary,
        }
