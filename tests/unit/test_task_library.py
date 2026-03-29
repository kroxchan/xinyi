from __future__ import annotations

import json


def test_task_library_bootstraps_seed_tasks_when_file_missing(tmp_path):
    from src.cognitive.task_library import TASK_DIMENSIONS, TaskLibrary

    tasks_file = tmp_path / "cognitive_tasks.json"
    storage_file = tmp_path / "task_results.json"

    tl = TaskLibrary(storage_path=str(storage_file), tasks_file=str(tasks_file))

    assert tl.get_total_count() >= len(TASK_DIMENSIONS)
    assert tasks_file.exists()
    loaded = json.loads(tasks_file.read_text("utf-8"))
    dims = {task["dimension"] for task in loaded}
    assert set(TASK_DIMENSIONS).issubset(dims)


def test_task_library_keeps_dynamic_tasks_and_adds_missing_seed_dimensions(tmp_path):
    from src.cognitive.task_library import TASK_DIMENSIONS, TaskLibrary

    tasks_file = tmp_path / "cognitive_tasks.json"
    tasks_file.write_text(
        json.dumps(
            [
                {
                    "id": "dyn_001",
                    "dimension": "contradiction_probe",
                    "prompt": "动态追问题",
                    "probes": ["tension"],
                }
            ],
            ensure_ascii=False,
        ),
        "utf-8",
    )
    storage_file = tmp_path / "task_results.json"

    tl = TaskLibrary(storage_path=str(storage_file), tasks_file=str(tasks_file))

    dims = {task["dimension"] for task in tl.tasks}
    assert "contradiction_probe" in dims
    assert set(TASK_DIMENSIONS).issubset(dims)


def test_task_library_refreshes_existing_seed_task_content(tmp_path):
    from src.cognitive.task_library import TaskLibrary

    tasks_file = tmp_path / "cognitive_tasks.json"
    tasks_file.write_text(
        json.dumps(
            [
                {
                    "id": "seed_emotional_response_001",
                    "dimension": "emotional_response",
                    "prompt": "旧题目",
                    "probes": ["old"],
                }
            ],
            ensure_ascii=False,
        ),
        "utf-8",
    )

    tl = TaskLibrary(storage_path=str(tmp_path / "task_results.json"), tasks_file=str(tasks_file))

    refreshed = next(task for task in tl.tasks if task["id"] == "seed_emotional_response_001")
    assert refreshed["prompt"] != "旧题目"
    assert "emotion regulation" in refreshed["theory_basis"]
