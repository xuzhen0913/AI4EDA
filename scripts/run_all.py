"""Own a complete local-service lifecycle, then release only the server we started."""
import argparse
import fcntl
import json
import os
import subprocess
import sys
from analog_agents.config import ROOT, project_path
from agents.sizing_agent.agent import validate_candidate
from scripts import service
from analog_agents.models import resolve


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-only',action='store_true',help='CPU validation and both PDFs, no GPU/model')
    parser.add_argument('--model',help='qwen | fable|sonnet|opus (Claude Code) | astra|sol|luna (Codex); same as SIZING_MODEL')
    args=parser.parse_args()
    base=ROOT/'circuits/two_stage_opamp'
    ref=(base/'reference/reference.spice').read_text()
    validate_candidate(ref,ref,json.loads((base/'specs/target.json').read_text()))
    command=[sys.executable,str(ROOT/'main.py')]
    if args.baseline_only:return subprocess.call(command+['--baseline-only'],cwd=ROOT)
    if args.model:os.environ['SIZING_MODEL']=args.model
    backend=resolve()[0]  # fail fast on a missing/unknown/conflicting selection
    if backend!='qwen':return subprocess.call(command,cwd=ROOT)  # cloud CLI models need no local GPU service
    project_path('logs').mkdir(exist_ok=True)
    # Hold across startup, optimization and cleanup. Other managed launches cannot race us.
    with project_path('logs/service.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if service.STATE.exists() and service.owned(json.loads(service.STATE.read_text())):
            raise RuntimeError('A managed Qwen service is already running. Use run_demo.sh to reuse it, or stop.sh first.')
        old=service.STATE.read_text() if service.STATE.exists() else None
        try:
            service.start(auto_gpu=True)
            return subprocess.call(command,cwd=ROOT)
        finally:
            if service.STATE.exists() and service.STATE.read_text()!=old:
                service.stop()

if __name__=='__main__':
    try:raise SystemExit(main())
    except KeyboardInterrupt:raise SystemExit(130)
