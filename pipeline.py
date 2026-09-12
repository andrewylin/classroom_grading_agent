import logging
import time

import config
import report_writer
import state_db
from classroom_client import ClassroomClient
from drive_client import DriveClient
from google_auth import get_credentials
from grader import grade_essay
from models import Recommendation

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("grading_pipeline")


def run_once(classroom: ClassroomClient, drive: DriveClient) -> int:
    """Returns the number of new recommendations written this pass."""
    new_count = 0
    for course_id in config.COURSE_IDS:
        coursework_list = classroom.list_coursework(course_id)
        for coursework in coursework_list:
            coursework_id = coursework["id"]
            title = coursework.get("title", "")
            instructions = coursework.get("description", "")

            rubric = classroom.get_rubric(course_id, coursework_id)
            if not rubric or not rubric.criteria:
                continue  # only auto-grade assignments that have a Classroom rubric attached

            submissions = classroom.list_turned_in_submissions(course_id, coursework_id)
            for sub in submissions:
                try:
                    revision_id = drive.get_revision_id(sub.drive_file_id)
                    if state_db.already_processed(sub.submission_id, revision_id):
                        continue

                    log.info("Grading submission %s (coursework=%s)", sub.submission_id, title)
                    essay_text = drive.export_text(sub.drive_file_id)
                    result = grade_essay(rubric, title, instructions, essay_text)
                    result.submission_id = sub.submission_id

                    student_name = classroom.get_student_name(sub.student_user_id)
                    recommendation = Recommendation(
                        course_id=course_id, coursework_id=coursework_id, coursework_title=title,
                        submission_id=sub.submission_id, student_user_id=sub.student_user_id,
                        student_name=student_name, doc_revision_id=revision_id, grade=result,
                    )
                    report_writer.append(recommendation)
                    state_db.mark_processed(sub.submission_id, revision_id, result.overall_score)

                    log.info(
                        "Recommendation written: %s — %.1f/%.0f",
                        student_name, result.overall_score, result.overall_max,
                    )
                    new_count += 1
                except Exception:
                    log.exception("Failed to grade submission %s", sub.submission_id)
    return new_count


def main():
    creds = get_credentials()
    classroom = ClassroomClient(creds)
    drive = DriveClient(creds)

    log.info("Starting grading pipeline (read-only). Watching courses: %s", config.COURSE_IDS)
    log.info("Recommendations will be appended to: %s", config.OUTPUT_PATH)
    while True:
        n = run_once(classroom, drive)
        if n:
            log.info("%d new recommendation(s) added to %s", n, config.OUTPUT_PATH)
        time.sleep(config.POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
