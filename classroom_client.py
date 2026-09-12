"""Thin, read-only wrapper around the Google Classroom API.

This client never patches grades or returns submissions - it only reads
coursework, rubrics, submissions, and student names.
"""
from __future__ import annotations
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from models import Rubric, RubricCriterion, RubricLevel, Submission


class ClassroomClient:
    def __init__(self, credentials):
        self.service = build("classroom", "v1", credentials=credentials)

    def list_coursework(self, course_id: str) -> list[dict]:
        resp = self.service.courses().courseWork().list(
            courseId=course_id, courseWorkStates=["PUBLISHED"]
        ).execute()
        return resp.get("courseWork", [])

    def get_rubric(self, course_id: str, coursework_id: str) -> Rubric | None:
        resp = self.service.courses().courseWork().rubrics().list(
            courseId=course_id, courseWorkId=coursework_id, pageSize=1
        ).execute()
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

    def list_turned_in_submissions(self, course_id: str, coursework_id: str) -> list[Submission]:
        resp = self.service.courses().courseWork().studentSubmissions().list(
            courseId=course_id, courseWorkId=coursework_id, states=["TURNED_IN"]
        ).execute()
        out = []
        for s in resp.get("studentSubmissions", []):
            attachments = s.get("assignmentSubmission", {}).get("attachments", [])
            drive_file_id = None
            for a in attachments:
                if "driveFile" in a:
                    drive_file_id = a["driveFile"]["id"]
                    break
            if not drive_file_id:
                continue  # skip non-Doc submissions (images, links, etc.) for now
            out.append(Submission(
                submission_id=s["id"], course_id=course_id, coursework_id=coursework_id,
                student_user_id=s["userId"], drive_file_id=drive_file_id, state=s["state"],
            ))
        return out

    def get_student_name(self, user_id: str) -> str:
        """Best-effort display name lookup. Falls back to the raw user ID if
        the profile can't be read (e.g. scope/permission edge cases)."""
        try:
            profile = self.service.userProfiles().get(userId=user_id).execute()
            return profile.get("name", {}).get("fullName", user_id)
        except HttpError:
            return user_id
