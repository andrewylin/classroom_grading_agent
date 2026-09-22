"""Local storage for calibration examples: essays you've hand-graded,
keyed by assignment (coursework_id), used as few-shot examples so the model
matches your grading style and rigor for that specific assignment."""
import json
import os

import config


def _path(coursework_id: str) -> str:
    return os.path.join(config.CALIBRATION_DIR, f"{coursework_id}.json")


def _empty_file(grading_instructions: str = "") -> dict:
    return {"grading_instructions": grading_instructions, "examples": []}


def _normalize_examples(examples: list[dict]) -> list[dict]:
    normalized = []
    for item in examples or []:
        if not isinstance(item, dict):
            continue
        normalized.append({k: v for k, v in item.items() if k != "grading_instructions"})
    return normalized


def _normalize_file(data) -> dict:
    if isinstance(data, list):
        grading_instructions = ""
        examples = []
        for item in data:
            if not isinstance(item, dict):
                continue
            if "grading_instructions" in item and not grading_instructions:
                grading_instructions = str(item.get("grading_instructions", ""))
            examples.append({k: v for k, v in item.items() if k != "grading_instructions"})
        return {"grading_instructions": grading_instructions, "examples": examples}

    if isinstance(data, dict):
        examples = data.get("examples", [])
        if not isinstance(examples, list):
            examples = []
        return {
            "grading_instructions": str(data.get("grading_instructions", "") or ""),
            "examples": _normalize_examples(examples),
        }

    return _empty_file()


def load_file(coursework_id: str) -> dict:
    path = _path(coursework_id)
    if not os.path.exists(path):
        return _empty_file()
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return _normalize_file(data)


def save_file(coursework_id: str, calibration_data: dict):
    os.makedirs(config.CALIBRATION_DIR, exist_ok=True)
    payload = _normalize_file(calibration_data)
    with open(_path(coursework_id), "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def load(coursework_id: str) -> list[dict]:
    return load_file(coursework_id).get("examples", [])


def save(coursework_id: str, examples: list[dict], grading_instructions: str | None = None):
    payload = load_file(coursework_id)
    payload["examples"] = _normalize_examples(examples)

    if grading_instructions is None:
        for item in examples or []:
            if isinstance(item, dict) and item.get("grading_instructions"):
                grading_instructions = str(item["grading_instructions"])
                break
    if grading_instructions is not None:
        payload["grading_instructions"] = grading_instructions
    save_file(coursework_id, payload)


def add_example(coursework_id: str, example: dict):
    payload = load_file(coursework_id)
    payload["examples"].append({k: v for k, v in example.items() if k != "grading_instructions"})
    save_file(coursework_id, payload)


def calibrated_submission_ids(coursework_id: str) -> set[str]:
    return {ex["submission_id"] for ex in load(coursework_id) if "submission_id" in ex}
