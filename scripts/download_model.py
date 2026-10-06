import json
from huggingface_hub import snapshot_download
from analog_agents.config import load_config, project_path

c = load_config()
path = snapshot_download(c["model_repo"], revision=c["model_revision"],
    local_dir=str(project_path(c["model_dir"])), max_workers=2,
    allow_patterns=["*.json", "*.safetensors", "*.txt", "*.jinja", "LICENSE", "README.md"])
project_path("logs/model_download.json").write_text(json.dumps({"path": path, "repo": c["model_repo"], "revision": c["model_revision"], "status": "complete"}, indent=2))
print(path)
