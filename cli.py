import builtins

import config
from classroom_client import ClassroomClient


def prompt_int(msg: str, min_v: int, max_v: int) -> int:
    while True:
        raw = builtins.input(msg).strip()
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
        course_id = builtins.input("Course ID: ").strip()
        if course_id:
            return course_id
