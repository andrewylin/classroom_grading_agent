"""Thin, read-only wrapper around the Google Classroom API.

This client never patches grades or returns submissions - it only reads
coursework, rubrics, submissions, and student names.
"""
from __future__ import annotations

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from models import Rubric, RubricCriterion, RubricLevel, Submission
from retry_utils import retry_on_transient_error


class ClassroomClient:
    def __init__(self, credentials):
        self.service = build("classroom", "v1", credentials=credentials)

    def list_courses(self) -> list[dict]:
        out = []
        page_token = None
        while True:
            req = self.service.courses().list(pageSize=100, pageToken=page_token, courseStates=["ACTIVE"])
            resp = retry_on_transient_error(
                lambda: req.execute(),
                "listing courses for active course selection",
            )
            for course in resp.get("courses", []):
                if course.get("courseState") in (None, "ACTIVE"):
                    out.append(course)
            page_token = resp.get("nextPageToken")
            if not page_token:
                return out

    def get_course_name(self, course_id: str) -> str:
        try:
            course = retry_on_transient_error(
                lambda: self.service.courses().get(id=course_id).execute(),
                f"getting course name for {course_id}",
            )
            return course.get("name", course_id)
        except HttpError:
            return course_id

    def list_coursework(self, course_id: str) -> list[dict]:
        out = []
        page_token = None
        while True:
            req = self.service.courses().courseWork().list(
                courseId=course_id,
                courseWorkStates=["PUBLISHED"],
                pageSize=100,
                pageToken=page_token,
            )
            resp = retry_on_transient_error(
                lambda: req.execute(),
                f"listing coursework for {course_id}",
            )
            out.extend(resp.get("courseWork", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                return out

    def get_rubric(self, course_id: str, coursework_id: str) -> Rubric | None:
        resp = retry_on_transient_error(
            lambda: self.service.courses().courseWork().rubrics().list(
                courseId=course_id, courseWorkId=coursework_id, pageSize=1
            ).execute(),
            f"getting rubric for coursework {coursework_id}",
        )
        rubrics = resp.get("rubrics", [])
        if not rubrics:
            return None
        r = rubrics[0]
        criteria = []
        for c in r.get("criteria", []):
            levels = [
                RubricLevel(score=lvl.get("points", 0), title=lvl.get("title", ""), description=lvl.get("description", ""))
                for lvl in c.get("levels", [])
            ]
            criteria.append(RubricCriterion(
                id=c.get("id", ""), title=c.get("title", ""),
                description=c.get("description", ""), levels=levels,
            ))
        return Rubric(id=r["id"], course_id=course_id, coursework_id=coursework_id, criteria=criteria)

    def get_coursework_max_points(self, course_id: str, coursework_id: str) -> float | None:
        try:
            coursework = retry_on_transient_error(
                lambda: self.service.courses().courseWork().get(courseId=course_id, id=coursework_id).execute(),
                f"reading maxPoints for coursework {coursework_id}",
            )
        except HttpError:
            return None
        max_points = coursework.get("maxPoints")
        if max_points is None:
            return None
        try:
            return float(max_points)
        except (TypeError, ValueError):
            return None

    def list_turned_in_submissions(self, course_id: str, coursework_id: str) -> list[Submission]:
        out = []
        page_token = None
        while True:
            resp = retry_on_transient_error(
                lambda: self.service.courses().courseWork().studentSubmissions().list(
                    courseId=course_id,
                    courseWorkId=coursework_id,
                    states=["TURNED_IN"],
                    pageSize=100,
                    pageToken=page_token,
                ).execute(),
                f"listing turned-in submissions for coursework {coursework_id}",
            )
            for s in resp.get("studentSubmissions", []):
                attachments = s.get("assignmentSubmission", {}).get("attachments", [])
                drive_file_id = None
                for a in attachments:
                    if "driveFile" in a:
                        drive_file_id = a["driveFile"]["id"]
                        break
                if not drive_file_id:
                    continue
                out.append(Submission(
                    submission_id=s["id"], course_id=course_id, coursework_id=coursework_id,
                    student_user_id=s["userId"], drive_file_id=drive_file_id, state=s["state"],
                ))
            page_token = resp.get("nextPageToken")
            if not page_token:
                return out

    def get_student_name(self, user_id: str) -> str:
        """Best-effort display name lookup. Falls back to the raw user ID if
        the profile can't be read (e.g. scope/permission edge cases)."""
        try:
            profile = retry_on_transient_error(
                lambda: self.service.userProfiles().get(userId=user_id).execute(),
                f"getting student profile for {user_id}",
            )
            return profile.get("name", {}).get("fullName", user_id)
        except HttpError:
            return user_id
