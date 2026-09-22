import logging

import calibration_store
import config
import report_writer
import state_db
from classroom_client import ClassroomClient
from cli import prompt_int, select_course_id
from drive_client import DriveClient
from google_auth import get_credentials
from grader import grade_essay
from models import Recommendation

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("grading_pipeline")


def select_coursework(classroom: ClassroomClient, course_id: str):
    courseworks = classroom.list_coursework(course_id)
    if not courseworks:
        print("No published coursework found for that course.")
        return None

    print("\nAssignments:")
    for i, cw in enumerate(courseworks):
        print(f"  [{i}] {cw.get('title')}")
    idx = prompt_int("\nPick an assignment number: ", 0, len(courseworks) - 1)
    return courseworks[idx]


def sort_submissions_by_student_first_name(classroom: ClassroomClient, submissions: list, name_cache: dict | None = None) -> list:
    cache = name_cache if name_cache is not None else {}

    def first_name_key(submission):
        if submission.student_user_id not in cache:
            cache[submission.student_user_id] = classroom.get_student_name(submission.student_user_id)
        name = cache[submission.student_user_id]
        parts = name.strip().split()
        first = parts[0].lower() if parts else ""
        return (first, name.lower())

    return sorted(submissions, key=first_name_key)


def run_once(classroom: ClassroomClient, drive: DriveClient, course_id: str, coursework: dict) -> int:
    """Returns the number of new recommendations written for one selected assignment."""
    coursework_id = coursework["id"]
    title = coursework.get("title", "")
    instructions = coursework.get("description", "")

    rubric = classroom.get_rubric(course_id, coursework_id)
    assignment_max_points = classroom.get_coursework_max_points(course_id, coursework_id)
    if rubric and rubric.criteria:
        assignment_instructions = instructions
        calibration_examples = calibration_store.load(coursework_id)[:config.MAX_CALIBRATION_EXAMPLES]
    else:
        log.warning("No rubric attached for %s/%s; prompting for custom grading guidance.", course_id, coursework_id)
        custom_instructions = input(
            "No rubric found for this assignment. Enter any additional grading instructions for the prompt "
            "(leave blank to use the assignment description only): "
        ).strip()
        assignment_instructions = "\n\n".join(
            part for part in [instructions, f"Additional teacher grading instructions: {custom_instructions}" if custom_instructions else ""] if part
        )
        calibration_examples = []
        rubric = None

    calibrated_ids = calibration_store.calibrated_submission_ids(coursework_id)
    already_graded_ids = report_writer.already_graded_submission_ids(course_id, title)
    regrade_already_graded = False
    if already_graded_ids:
        print(f"{len(already_graded_ids)} submission(s) already graded for this assignment in {config.OUTPUT_PATH}.")
        response = input("Regrade already-graded submissions? [y/N]: ").strip().lower()
        regrade_already_graded = response in {"y", "yes"}

    student_name_cache = {}
    submissions = sort_submissions_by_student_first_name(
        classroom,
        classroom.list_turned_in_submissions(course_id, coursework_id),
        student_name_cache,
    )

    new_count = 0
    skipped_count = 0
    failed_count = 0
    for sub in submissions:
        if sub.submission_id in calibrated_ids:
            skipped_count += 1
            continue
        if sub.submission_id in already_graded_ids and not regrade_already_graded:
            skipped_count += 1
            continue

        try:
            revision_id = drive.get_revision_id(sub.drive_file_id)
            if state_db.already_processed(sub.submission_id, revision_id):
                skipped_count += 1
                continue

            log.info("Grading submission %s", sub.submission_id)
            essay_text = drive.export_text(sub.drive_file_id)
            result = grade_essay(
                rubric,
                title,
                assignment_instructions,
                essay_text,
                calibration_examples,
                fallback_max_points=assignment_max_points,
            )
            result.submission_id = sub.submission_id

            if sub.student_user_id not in student_name_cache:
                student_name_cache[sub.student_user_id] = classroom.get_student_name(sub.student_user_id)
            student_name = student_name_cache[sub.student_user_id]
            recommendation = Recommendation(
                course_id=course_id, coursework_id=coursework_id, coursework_title=title,
                submission_id=sub.submission_id, student_user_id=sub.student_user_id,
                student_name=student_name, doc_revision_id=revision_id, grade=result,
            )
            report_writer.append(recommendation)
            state_db.mark_processed(sub.submission_id, revision_id, result.overall_score)

            log.info(
                "Recommendation written: %s — %.1f/%.0f - %s",
                student_name, result.overall_score, result.overall_max, result.feedback_summary[:50].replace("\n", " ") + ("..." if len(result.feedback_summary) > 50 else "")
            )
            new_count += 1
        except Exception:
            failed_count += 1
            log.exception("Failed to grade submission %s", sub.submission_id)

    log.info(
        "Run summary for %s/%s: %d new, %d skipped, %d failed.",
        course_id, coursework_id, new_count, skipped_count, failed_count,
    )
    return new_count


def main():
    creds = get_credentials()
    classroom = ClassroomClient(creds)
    drive = DriveClient(creds)

    course_id = select_course_id(classroom)
    coursework = select_coursework(classroom, course_id)
    if coursework is None:
        return

    coursework_id = coursework["id"]
    course_name = classroom.get_course_name(course_id)
    log.info("Starting grading run for course %s (%s) assignment %s", course_name, course_id, coursework.get("title", coursework_id))
    log.info("Recommendations will be appended to: %s", config.OUTPUT_PATH)

    n = run_once(classroom, drive, course_id, coursework)
    if n:
        log.info("%d new recommendation(s) added to %s", n, config.OUTPUT_PATH)
    else:
        log.info("No new recommendations written for %s.", coursework.get("title", coursework_id))


if __name__ == "__main__":
    main()
