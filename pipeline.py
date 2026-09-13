import logging

import calibration_store
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


def prompt_int(msg: str, min_v: int, max_v: int) -> int:
    while True:
        raw = input(msg).strip()
        try:
            v = int(raw)
            if min_v <= v <= max_v:
                return v
        except ValueError:
            pass
        print(f"  enter a whole number between {min_v} and {max_v}")


def course_label(classroom: ClassroomClient, course_id: str) -> str:
    name = classroom.get_course_name(course_id)
    return f"{name} ({course_id})" if name and name != course_id else course_id


def select_course_id(classroom: ClassroomClient) -> str:
    if config.COURSE_IDS:
        print("\nCourses:")
        for i, course_id in enumerate(config.COURSE_IDS):
            print(f"  [{i}] {course_label(classroom, course_id)}")
        idx = prompt_int("\nPick a course number: ", 0, len(config.COURSE_IDS) - 1)
        return config.COURSE_IDS[idx]

    available = classroom.list_courses()
    if available:
        print("\nCourses:")
        for i, course in enumerate(available):
            course_id = course.get("id")
            course_name = course.get("name") or course_id
            print(f"  [{i}] {course_name} ({course_id})")
        idx = prompt_int("\nPick a course number: ", 0, len(available) - 1)
        return available[idx].get("id")

    while True:
        course_id = input("Course ID: ").strip()
        if course_id:
            return course_id


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


def sort_submissions_by_student_first_name(classroom: ClassroomClient, submissions: list) -> list:
    def first_name_key(submission):
        name = classroom.get_student_name(submission.student_user_id)
        parts = name.strip().split()
        first = parts[0].lower() if parts else ""
        return (first, name.lower())

    return sorted(submissions, key=first_name_key)


def run_once(classroom: ClassroomClient, drive: DriveClient, course_id: str, coursework_id: str) -> int:
    """Returns the number of new recommendations written for one selected assignment."""
    coursework = next((cw for cw in classroom.list_coursework(course_id) if cw["id"] == coursework_id), None)
    if coursework is None:
        raise ValueError(f"Coursework {coursework_id} not found in course {course_id}")

    title = coursework.get("title", "")
    instructions = coursework.get("description", "")

    rubric = classroom.get_rubric(course_id, coursework_id)
    if not rubric or not rubric.criteria:
        log.warning("Skipping %s/%s: no rubric attached.", course_id, coursework_id)
        return 0

    calibration_examples = calibration_store.load(coursework_id)[:config.MAX_CALIBRATION_EXAMPLES]
    calibrated_ids = calibration_store.calibrated_submission_ids(coursework_id)

    submissions = sort_submissions_by_student_first_name(
        classroom, classroom.list_turned_in_submissions(course_id, coursework_id)
    )
    new_count = 0
    for sub in submissions:
        if sub.submission_id in calibrated_ids:
            continue

        try:
            revision_id = drive.get_revision_id(sub.drive_file_id)
            if state_db.already_processed(sub.submission_id, revision_id):
                continue

            log.info("Grading submission %s", sub.submission_id)
            essay_text = drive.export_text(sub.drive_file_id)
            result = grade_essay(rubric, title, instructions, essay_text, calibration_examples)
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
                "Recommendation written: %s — %.1f/%.0f - %s",
                student_name, result.overall_score, result.overall_max, result.feedback_summary[:50].replace("\n", " ") + ("..." if len(result.feedback_summary) > 50 else "")
            )
            new_count += 1
        except Exception:
            log.exception("Failed to grade submission %s", sub.submission_id)
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

    n = run_once(classroom, drive, course_id, coursework_id)
    if n:
        log.info("%d new recommendation(s) added to %s", n, config.OUTPUT_PATH)
    else:
        log.info("No new recommendations written for %s.", coursework.get("title", coursework_id))


if __name__ == "__main__":
    main()
