import logging
import time

import config
import state_db
from classroom_client import ClassroomClient
from drive_client import DriveClient
from google_auth import get_credentials
from grader import grade_essay

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("grading_pipeline")


def run_once(classroom: ClassroomClient, drive: DriveClient):
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
                    if state_db.already_graded(sub.submission_id, revision_id):
                        continue

                    log.info("Grading submission %s (coursework=%s)", sub.submission_id, title)
                    essay_text = drive.export_text(sub.drive_file_id)
                    result = grade_essay(rubric, title, instructions, essay_text)
                    result.submission_id = sub.submission_id

                    classroom.set_draft_grade(course_id, coursework_id, sub.submission_id, result.overall_score)
                    drive.post_comment(sub.drive_file_id, result.as_comment_text())

                    returned = False
                    if config.AUTO_RETURN:
                        classroom.set_assigned_grade_and_return(
                            course_id, coursework_id, sub.submission_id, result.overall_score
                        )
                        returned = True

                    state_db.mark_graded(sub.submission_id, revision_id, result.overall_score, returned)
                    log.info(
                        "Submission %s: %.1f/%.0f (%s)",
                        sub.submission_id, result.overall_score, result.overall_max,
                        "returned" if returned else "draft only",
                    )
                except Exception:
                    log.exception("Failed to grade submission %s", sub.submission_id)


def main():
    creds = get_credentials()
    classroom = ClassroomClient(creds)
    drive = DriveClient(creds)

    log.info("Starting grading pipeline. Watching courses: %s", config.COURSE_IDS)
    while True:
        run_once(classroom, drive)
        time.sleep(config.POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
