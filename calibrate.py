"""Interactive calibration: pick a course + assignment, then walk through its
turned-in submissions one at a time. For each one you choose, enter your own
rubric scores and feedback. These get saved and used as few-shot examples
when grading that specific assignment going forward.

Run: python calibrate.py
"""
import config
import calibration_store
from classroom_client import ClassroomClient
from drive_client import DriveClient
from google_auth import get_credentials

ESSAY_PREVIEW_CHARS = 3000


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


def format_course_label(classroom: ClassroomClient, course_id: str) -> str:
    name = classroom.get_course_name(course_id)
    return f"{name} ({course_id})" if name and name != course_id else course_id


def select_course_id(classroom: ClassroomClient) -> str:
    if config.COURSE_IDS:
        print("\nCourses:")
        for i, course_id in enumerate(config.COURSE_IDS):
            print(f"  [{i}] {format_course_label(classroom, course_id)}")
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


def main():
    creds = get_credentials()
    classroom = ClassroomClient(creds)
    drive = DriveClient(creds)

    course_id = select_course_id(classroom)
    courseworks = classroom.list_coursework(course_id)
    if not courseworks:
        print("No published coursework found for that course.")
        return

    print("\nAssignments:")
    for i, cw in enumerate(courseworks):
        print(f"  [{i}] {cw.get('title')}")
    idx = prompt_int("\nPick an assignment number: ", 0, len(courseworks) - 1)
    coursework = courseworks[idx]
    coursework_id = coursework["id"]

    rubric = classroom.get_rubric(course_id, coursework_id)
    if rubric and rubric.criteria:
        grading_instructions = coursework.get("description", "")
    else:
        print("This assignment has no Classroom rubric attached; you'll provide custom grading guidance.")
        grading_instructions = input(
            "Enter any additional grading instructions for this assignment (leave blank to just use the assignment description): "
        ).strip()
        rubric = None

    submissions = classroom.list_turned_in_submissions(course_id, coursework_id)
    if not submissions:
        print("No turned-in submissions found for this assignment yet.")
        return

    already = calibration_store.calibrated_submission_ids(coursework_id)
    print(f"\n{len(submissions)} turned-in submission(s). {len(already)} already calibrated for this assignment.\n")

    for sub in submissions:
        if sub.submission_id in already:
            continue

        student_name = classroom.get_student_name(sub.student_user_id)
        essay_text = drive.export_text(sub.drive_file_id)

        print("=" * 70)
        print(f"Student: {student_name}  (submission {sub.submission_id})")
        print("=" * 70)
        preview = essay_text[:ESSAY_PREVIEW_CHARS]
        if len(essay_text) > ESSAY_PREVIEW_CHARS:
            preview += "\n... [truncated for display - full text is still used for calibration]"
        print(preview)
        print("-" * 70)

        choice = input("\nUse this submission as a calibration example? [y/n/q to stop]: ").strip().lower()
        if choice == "q":
            break
        if choice != "y":
            continue

        if rubric and rubric.criteria:
            criterion_scores = {}
            for c in rubric.criteria:
                print(f"\nCriterion: {c.title} (0-{c.max_score})")
                for lvl in sorted(c.levels, key=lambda l: -l.score):
                    print(f"  {lvl.score}: {lvl.title} - {lvl.description}")
                score = prompt_int(f"Your score for '{c.title}': ", 0, c.max_score)
                criterion_scores[c.id] = {"score": score}
        else:
            print("\nOverall score (0-100):")
            score = prompt_int("Your overall score for this essay: ", 0, 100)
            criterion_scores = {"overall": {"score": score}}

        feedback_summary = input("\nYour overall feedback summary for this student: ").strip()

        calibration_store.add_example(coursework_id, {
            "submission_id": sub.submission_id,
            "essay_text": essay_text,
            "criterion_scores": criterion_scores,
            "feedback_summary": feedback_summary,
            "grading_instructions": grading_instructions,
        })
        print(f"Saved calibration example for {student_name}.\n")

    n = len(calibration_store.load(coursework_id))
    print(f"\nDone. {n} calibration example(s) stored for this assignment in calibration/{coursework_id}.json")


if __name__ == "__main__":
    main()
