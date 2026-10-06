"""Single-GPU, loopback-only service. Stop only the process group we created."""
import fcntl
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from analog_agents.config import load_config, project_path, ROOT

STATE = project_path("logs/service.json")

def birth(pid):
    try:
        return open(f"/proc/{pid}/stat").read().split(") ", 1)[1].split()[19]
    except FileNotFoundError:
        return None

def owned(state):
    return birth(state["pid"]) == state["birth"]

def stop():
    if not STATE.exists():
        print("No managed service.")
        return
    state = json.loads(STATE.read_text())
    if owned(state):
        os.killpg(state["pid"], signal.SIGTERM)
        for _ in range(60):
            if not owned(state):
                break
            # A reaped-by-parent zombie cannot hold GPU resources.
            stat = open(f"/proc/{state['pid']}/stat").read().split(") ", 1)[1]
            if stat.startswith("Z"):
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("Graceful stop timed out; inspect logs before any further action")
    STATE.unlink()
    print("Managed Qwen service stopped.")

def start():
    c = load_config()
    if STATE.exists() and owned(json.loads(STATE.read_text())):
        raise RuntimeError("Managed service already running; use stop.sh first")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", c["port"]))
    lines = subprocess.check_output(["nvidia-smi", f"--id={c['gpu']}",
        "--query-gpu=uuid,memory.used,memory.total,utilization.gpu", "--format=csv,noheader,nounits"], text=True).strip()
    uuid, used, total, util = [s.strip() for s in lines.split(",")]
    if int(used) > 1024 or int(util) > 5:
        raise RuntimeError(f"GPU {c['gpu']} is busy: {lines}. Choose an idle GPU; no process will be killed.")
    model = project_path(c["model_dir"])
    if not (model / "config.json").exists():
        raise RuntimeError("Model absent. Run scripts/download_model.py first.")
    env = os.environ.copy()
    # vLLM 0.8.5's NVML mapper requires a numeric CUDA_VISIBLE_DEVICES value.
    env.update(CUDA_VISIBLE_DEVICES=str(c["gpu"]), CUDA_DEVICE_ORDER="PCI_BUS_ID", VLLM_USE_V1="0",
               HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", VLLM_WORKER_MULTIPROC_METHOD="spawn")
    cmd = [sys.executable, "-m", "vllm.entrypoints.openai.api_server", "--model", str(model),
        "--served-model-name", c["served_model"], "--host", "127.0.0.1", "--port", str(c["port"]),
        "--dtype", "bfloat16", "--max-model-len", str(c["context_length"]),
        "--gpu-memory-utilization", str(c["gpu_memory_utilization"]), "--tensor-parallel-size", "1",
        "--max-num-seqs", "2", "--enforce-eager", "--disable-log-requests", "--disable-frontend-multiprocessing",
        "--guided-decoding-backend", "xgrammar"]
    with project_path("logs/qwen.log").open("a") as log:
        proc = subprocess.Popen(cmd, env=env, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    STATE.write_text(json.dumps({"pid": proc.pid, "birth": birth(proc.pid), "gpu_uuid": uuid, "port": c["port"], "command": cmd}, indent=2))
    print(f"Starting PID {proc.pid} on GPU {c['gpu']} ({uuid}); see logs/qwen.log", flush=True)
    for _ in range(300):
        if proc.poll() is not None:
            STATE.unlink(missing_ok=True)
            raise RuntimeError(f"Server exited with {proc.returncode}; see logs/qwen.log")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{c['port']}/health", timeout=2) as response:
                if response.status == 200:
                    print(f"Ready: http://127.0.0.1:{c['port']}/v1")
                    return
        except (OSError, TimeoutError):
            pass
        time.sleep(2)
    stop()
    raise RuntimeError("Service startup timed out")

if __name__ == "__main__":
    with project_path("logs/service.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        {"start": start, "stop": stop}[sys.argv[1]]()
