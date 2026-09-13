"""Writes grading recommendations to a local CSV file. Nothing in this
module talks to Google APIs - it's purely local output."""
import csv
import os

import config
from models import Recommendation

FIELDNAMES = [
    "course_id", "coursework_title", "student_name", "student_user_id",
    "submission_id", "recommended_grade", "max_grade",
    "criteria_breakdown", "feedback_summary",
]


def append(recommendation: Recommendation):
    file_exists = os.path.exists(config.OUTPUT_PATH)
    with open(config.OUTPUT_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if not file_exists:
            writer.writeheader()
        writer.writerow(recommendation.to_row())
