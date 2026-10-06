import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def project_path(relative):
    path = (ROOT / relative).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError(f"Path escapes project: {relative}")
    return path

def load_config():
    cfg = json.loads(project_path("config/settings.json").read_text())
    project_path(cfg["model_dir"])
    assert isinstance(cfg["gpu"], int) and cfg["gpu"] >= 0
    assert 1024 <= cfg["port"] <= 65535
    assert 0.1 <= cfg["gpu_memory_utilization"] <= 0.6
    assert 1024 <= cfg["context_length"] <= 32768
    return cfg
