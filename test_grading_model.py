import unittest

from classroom_client import ClassroomClient
from grader import _build_prompt, _build_schema, make_fallback_rubric, validate_rubric
from models import CriterionScore, Rubric, RubricCriterion, RubricLevel, Submission
from pipeline import sort_submissions_by_student_first_name


class GradingModelTests(unittest.TestCase):
    def test_schema_includes_criterion_justification(self):
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
        self.assertIn("justification", schema["properties"]["criteria"]["properties"]["c1"]["properties"])

    def test_prompt_truncates_long_essays(self):
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
        prompt = _build_prompt(
            rubric,
            "Essay",
            "Write an essay",
            "A" * 50000,
            calibration_examples=[],
        )
        self.assertIn("[truncated", prompt)
        self.assertLess(len(prompt), 25000)

    def test_zero_point_rubric_is_rejected(self):
        rubric = Rubric(
            id="rubric-1",
            course_id="course-1",
            coursework_id="cw-1",
            criteria=[
                RubricCriterion(
                    id="c1",
                    title="Title",
                    description="Desc",
                    levels=[RubricLevel(score=0, title="Low", description=""), RubricLevel(score=0, title="High", description="")],
                )
            ],
        )
        with self.assertRaises(ValueError):
            validate_rubric(rubric)

    def test_fallback_rubric_uses_assignment_max_points(self):
        rubric = make_fallback_rubric(15)
        self.assertEqual(15, rubric.max_total)
        self.assertEqual(15, rubric.criteria[0].max_score)

    def test_list_courses_filters_out_archived_courses(self):
        class FakeListCall:
            def execute(self):
                return {"courses": [{"id": "a", "courseState": "ARCHIVED"}, {"id": "b", "courseState": "ACTIVE"}], "nextPageToken": None}

        class FakeCourses:
            def list(self, pageSize, pageToken=None, courseStates=None):
                self.last_states = courseStates
                return FakeListCall()

        class FakeService:
            def __init__(self):
                self.courses_obj = FakeCourses()

            def courses(self):
                return self.courses_obj

        client = ClassroomClient.__new__(ClassroomClient)
        client.service = FakeService()
        courses = client.list_courses()
        self.assertEqual(["b"], [c["id"] for c in courses])
        self.assertEqual(["ACTIVE"], client.service.courses_obj.last_states)

    def test_missing_max_points_returns_none(self):
        class FakeCourseWork:
            def get(self, courseId, id):
                class Resp:
                    def execute(self):
                        return {"id": "cw-1", "title": "No points assignment"}
                return Resp()

        class FakeService:
            def courseWork(self):
                return FakeCourseWork()

        client = ClassroomClient.__new__(ClassroomClient)
        client.service = FakeService()
        self.assertIsNone(client.get_coursework_max_points("course-1", "cw-1"))

    def test_criterion_score_keeps_justification_field(self):
        score = CriterionScore(
            criterion_id="c1",
            criterion_title="Title",
            score=3,
            max_score=4,
            justification="Strong evidence and clear reasoning.",
        )
        self.assertEqual(score.score, 3)
        self.assertEqual(score.max_score, 4)
        self.assertEqual(score.justification, "Strong evidence and clear reasoning.")

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
