"""Local storage for calibration examples: essays you've hand-graded,
keyed by assignment (coursework_id), used as few-shot examples so the model
matches your grading style and rigor for that specific assignment."""
import json
import os

import config


def _path(coursework_id: str) -> str:
    return os.path.join(config.CALIBRATION_DIR, f"{coursework_id}.json")


def load(coursework_id: str) -> list[dict]:
    path = _path(coursework_id)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(coursework_id: str, examples: list[dict]):
    os.makedirs(config.CALIBRATION_DIR, exist_ok=True)
    with open(_path(coursework_id), "w", encoding="utf-8") as f:
        json.dump(examples, f, indent=2)


def add_example(coursework_id: str, example: dict):
    examples = load(coursework_id)
    examples.append(example)
    save(coursework_id, examples)


def calibrated_submission_ids(coursework_id: str) -> set[str]:
    return {ex["submission_id"] for ex in load(coursework_id)}
