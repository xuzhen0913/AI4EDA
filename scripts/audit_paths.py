"""Audit project-owned artifact trees and configured writable locations, not private home files."""
import json
import os
from pathlib import Path
from analog_agents.config import ROOT, project_path

def main():
    keys = ['TMPDIR', 'TMP', 'TEMP', 'XDG_CACHE_HOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_STATE_HOME',
        'UV_CACHE_DIR', 'PIP_CACHE_DIR', 'HF_HOME', 'OUTLINES_CACHE_DIR',
        'TORCH_HOME', 'TORCH_EXTENSIONS_DIR', 'TRITON_CACHE_DIR', 'CUDA_CACHE_PATH', 'VLLM_CACHE_ROOT',
        'VLLM_CONFIG_ROOT', 'NUMBA_CACHE_DIR', 'MPLCONFIGDIR']
    paths = {key: str(project_path(os.environ[key])) for key in keys}
    # Explicit retained general-purpose tools; no arbitrary project-path escape.
    allowed_tools = {
        'UV_PYTHON_INSTALL_DIR': Path('/home/xu/.runtime/python'),
        'UV_PYTHON_BIN_DIR': Path('/home/xu/.runtime/bin'),
        'PROJECT_VENV': Path('/home/xu/.venv'),
        'PROJECT_PYTHON': Path('/home/xu/.venv/bin/python'),
        'PROJECT_UV': Path('/home/xu/.runtime/tools/bin/uv'),
    }
    shared = {}
    for key, expected in allowed_tools.items():
        actual = Path(os.environ[key]).resolve()
        if actual != expected.resolve() or not actual.exists():
            raise ValueError(f'Unexpected retained tool path: {key}={actual}')
        shared[key] = str(actual)
    links = []
    trees = ['.runtime', 'models', 'scripts', 'config', 'prompts', 'analog_agents', 'tests', 'logs', 'outputs', 'docs']
    files = 0
    for tree in trees:
        for base, dirs, names in os.walk(project_path(tree), followlinks=False):
            files += len(names)
            for name in dirs+names:
                path = project_path(base) / name
                if path.is_symlink():
                    target = path.resolve()
                    links.append({'path': str(path), 'target': str(target), 'inside_project': target.is_relative_to(ROOT)})
    outside = [item for item in links if not item['inside_project']]
    report = {'status': 'passed' if not outside else 'review_required', 'configured_write_paths': paths,
        'retained_general_purpose_tools': shared,
        'artifact_files_checked': files, 'symlinks_checked': len(links), 'external_symlinks': outside,
        'scope': 'Configured paths and project artifact symlinks; not a kernel audit of every dependency syscall.'}
    project_path('logs/path_audit.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    assert not outside, outside

if __name__ == '__main__':
    main()
