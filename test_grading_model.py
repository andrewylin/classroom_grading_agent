import unittest

from grader import _build_schema
from models import CriterionScore, Rubric, RubricCriterion, RubricLevel


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


if __name__ == "__main__":
    unittest.main()
