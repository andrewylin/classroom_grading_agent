import unittest

from grader import _build_schema
from models import CriterionScore, Rubric, RubricCriterion, RubricLevel, Submission
from pipeline import sort_submissions_by_student_first_name


class GradingModelTests(unittest.TestCase):
    def test_schema_omits_criterion_justification(self):
        rubric = Rubric(
            id="rubric-1",
            course_id="course-1",
            coursework_id="cw-1",
            criteria=[
                RubricCriterion(
                    id="c1",
                    title="Title",
                    description="Desc",
                    levels=[RubricLevel(score=0, title="Low", description=""), RubricLevel(score=4, title="High", description="")],
                )
            ],
        )
        schema = _build_schema(rubric)
        self.assertNotIn("justification", schema["properties"]["criteria"]["properties"]["c1"]["properties"])

    def test_criterion_score_has_no_justification_field(self):
        score = CriterionScore(criterion_id="c1", criterion_title="Title", score=3, max_score=4)
        self.assertEqual(score.score, 3)
        self.assertEqual(score.max_score, 4)
        self.assertFalse(hasattr(score, "justification"))

    def test_submissions_are_sorted_by_student_first_name(self):
        class FakeClassroom:
            def get_student_name(self, user_id):
                names = {
                    "u-3": "Zoe Adams",
                    "u-1": "Alice Brown",
                    "u-2": "Mason Chen",
                }
                return names[user_id]

        submissions = [
            Submission("s-3", "course", "cw", "u-3", "file-3", "TURNED_IN"),
            Submission("s-1", "course", "cw", "u-1", "file-1", "TURNED_IN"),
            Submission("s-2", "course", "cw", "u-2", "file-2", "TURNED_IN"),
        ]

        ordered = sort_submissions_by_student_first_name(FakeClassroom(), submissions)
        self.assertEqual(["s-1", "s-2", "s-3"], [s.submission_id for s in ordered])


if __name__ == "__main__":
    unittest.main()
