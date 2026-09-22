"""Interactive calibration: pick a course + assignment, then walk through its
turned-in submissions one at a time. For each one you choose, enter your own
rubric scores and feedback. These get saved and used as few-shot examples
when grading that specific assignment going forward.

Run: python calibrate.py
"""
import config
import calibration_store
import report_writer
from classroom_client import ClassroomClient
from cli import prompt_int, select_course_id
from drive_client import DriveClient
from google_auth import get_credentials
from models import Submission
from pipeline import sort_submissions_by_student_first_name

ESSAY_PREVIEW_CHARS = 3000


def select_submission_for_calibration(
    submissions: list[Submission],
    already_calibrated_ids: set[str],
    get_student_name,
    input_func=input,
    name_cache: dict[str, str] | None = None,
) -> Submission | None:
    cache = name_cache if name_cache is not None else {}

    class StudentNameProviderAdapter:
        def __init__(self, lookup):
            self._lookup = lookup

        def get_student_name(self, user_id: str) -> str:
            return self._lookup(user_id)

    def lookup_student_name(user_id: str) -> str:
        if user_id not in cache:
            cache[user_id] = get_student_name(user_id)
        return cache[user_id]

    student_name_provider = StudentNameProviderAdapter(lookup_student_name)
    available: list[Submission] = [
        sub for sub in sort_submissions_by_student_first_name(student_name_provider, submissions, name_cache=cache)
        if sub.submission_id not in already_calibrated_ids
    ]
    if not available:
        return None

    print("\nAvailable submissions for calibration:")
    for i, sub in enumerate(available):
        student_name = lookup_student_name(sub.student_user_id)
        print(f"  [{i}] {student_name} (submission {sub.submission_id})")

    while True:
        raw = input_func("\nPick a submission number to calibrate: ").strip()
        try:
            idx = int(raw)
            if 0 <= idx < len(available):
                return available[idx]
        except ValueError:
            pass
        print("  enter a valid submission number from the list above.")


def prompt_to_continue_calibrating(input_func=input) -> bool:
    return input_func("\nContinue calibrating another submission? [y/N]: ").strip().lower() in {"y", "yes"}


def prompt_for_grading_instructions(existing_instructions: str, default_instructions: str, input_func=input) -> str:
    existing = existing_instructions.strip()
    if not existing:
        return default_instructions

    while True:
        print("\nExisting grading instructions for this assignment:")
        print(existing)
        response = input_func("Keep these grading instructions? [Y/n/replace]: ").strip().lower()
        if response in {"", "y", "yes"}:
            return existing
        if response in {"n", "no"}:
            return default_instructions
        if response in {"r", "replace"}:
            replacement = input_func(
                "Enter replacement grading instructions (leave blank to use the assignment description): "
            ).strip()
            return replacement or default_instructions
        print("  Please enter Y, N, or replace.")


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
    assignment_max_points = classroom.get_coursework_max_points(course_id, coursework_id)
    existing_grading_instructions = calibration_store.load_file(coursework_id).get("grading_instructions", "")
    default_grading_instructions = coursework.get("description", "")

    if rubric and rubric.criteria:
        grading_instructions = prompt_for_grading_instructions(
            existing_grading_instructions,
            default_grading_instructions,
        )
    else:
        print("This assignment has no Classroom rubric attached; you'll provide custom grading guidance.")
        if existing_grading_instructions:
            grading_instructions = prompt_for_grading_instructions(
                existing_grading_instructions,
                default_grading_instructions,
            )
        else:
            grading_instructions = input(
                "Enter any additional grading instructions for this assignment (leave blank to just use the assignment description): "
            ).strip()
        rubric = None

    submissions = classroom.list_turned_in_submissions(course_id, coursework_id)
    if not submissions:
        print("No turned-in submissions found for this assignment yet.")
        return

    already = calibration_store.calibrated_submission_ids(coursework_id)
    already_graded = report_writer.already_graded_submission_ids(
        course_id,
        coursework.get("title", ""),
        coursework_id=coursework_id,
    )
    print(
        f"\n{len(submissions)} turned-in submission(s). "
        f"{len(already)} already calibrated for this assignment. "
        f"{len(already_graded)} already graded for this assignment in {config.OUTPUT_PATH}.\n"
    )

    name_cache: dict[str, str] = {}
    while True:
        selected_submission = select_submission_for_calibration(submissions, already, classroom.get_student_name, name_cache=name_cache)
        if selected_submission is None:
            print("No remaining submissions left to calibrate for this assignment.")
            return

        student_name = classroom.get_student_name(selected_submission.student_user_id)
        essay_text = drive.export_text(selected_submission.drive_file_id)

        print("=" * 70)
        print(f"Student: {student_name}  (submission {selected_submission.submission_id})")
        print("=" * 70)
        preview = essay_text[:ESSAY_PREVIEW_CHARS]
        if len(essay_text) > ESSAY_PREVIEW_CHARS:
            preview += "\n... [truncated for display - full text is still used for calibration]"
        print(preview)
        print("-" * 70)

        choice = input("\nUse this submission as a calibration example? [y/n]: ").strip().lower()
        if choice != "y":
            print("No calibration example saved for this submission.")
            if not prompt_to_continue_calibrating():
                return
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
            max_points = assignment_max_points if assignment_max_points is not None else 100.0
            print(f"\nOverall score (0-{max_points}):")
            score = prompt_int("Your overall score for this essay: ", 0, int(max_points))
            criterion_scores = {"overall": {"score": score}}

        feedback_summary = input("\nYour overall feedback summary for this student: ").strip()

        cal_file = calibration_store.load_file(coursework_id)
        cal_file["grading_instructions"] = grading_instructions
        cal_file["examples"].append({
            "submission_id": selected_submission.submission_id,
            "essay_text": essay_text,
            "criterion_scores": criterion_scores,
            "feedback_summary": feedback_summary,
        })
        calibration_store.save_file(coursework_id, cal_file)
        already.add(selected_submission.submission_id)
        print(f"Saved calibration example for {student_name}.\n")

        n = len(calibration_store.load(coursework_id))
        print(f"\nDone. {n} calibration example(s) stored for this assignment in calibration/{coursework_id}.json")

        if not prompt_to_continue_calibrating():
            return


if __name__ == "__main__":
    main()
