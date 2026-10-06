"""Chinese edition of an existing experiment; no simulation or model inference."""
from pathlib import Path
from simulator.report_generator import generate as render

def generate(results):
    return render(results,language='zh')

if __name__=='__main__':
    print(generate(Path(__file__).resolve().parents[1]/'circuits/two_stage_opamp/results'))
