"""Rebuild design_memory.txt from everything simulated so far (no model, no simulation): the archived runs under
circuits/<circuit>/results/runs/, the current results/, the verified designs quoted by the references (@verified) and
a few points documented in the reference notes.

    python scripts/build_memory.py [--circuit opamp] [--dry-run]

Only records made with the closed-loop testbench are used (older open-loop records measure another thing). The file is
rewritten from scratch, so running it twice gives the same result."""
import argparse
import json
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analog_agents import memory as design_memory
from analog_agents.reference import load_references
from analog_agents.search import spec_check
from analog_agents.spice import number, parameters

ROOT = Path(__file__).resolve().parents[1]
# parameter names that older netlists spelled differently: new name -> function of the old parameter dict
LEGACY = {'R_RZ': lambda p: str(number(p['RSH_RZ']) * number(p['L_RZ']) / number(p['W_RZ']))
          if {'RSH_RZ', 'L_RZ', 'W_RZ'} <= set(p) else None}
# documented in a reference's notes (and tests/test_pdk.py): found by an ngspice bias search, the loop holds out at VCM but
# the devices are in weak inversion, so the DC gate (overdrive criterion) fails
EXTRA_DC_FAILS = {'folded_cascode_pmos_input': [dict(
    L_IN='0.15', L_TAIL='0.15', W_IN='44.58', W_TAIL='41.93', W_FOLD='25.45', W_CAS='24.6', W_LOAD='8.06',
    VBP_TAIL='1.065', VBN_FOLD='0.591', VBN_CAS='0.787', VBP_CAS='0.993')]}


def run_points(results, refs, stats):
    """(reference id, conditions key, targets, [(status, metrics, params)]) for every round of one results folder."""
    specs = json.loads((results / 'specs.json').read_text())
    for rdir in sorted(results.glob('round_*')):
        try:
            ref_id = json.loads((rdir / 'summary.json').read_text())['reference']
        except (OSError, ValueError, KeyError):
            continue
        ref, points = refs.get(ref_id), []
        for record in sorted((rdir / 'logs').glob('simulation_*.json')):
            data = json.loads(record.read_text())
            if data.get('bias') != 'closed_loop':
                stats['open_loop_skipped'] += 1
                continue
            dc_only_failure = data['analysis_mode'] == 'dc' and not data['dc_passed']
            if not (dc_only_failure or data['analysis_mode'] == 'full'):
                continue   # a DC-only pass is followed by the full simulation of the same candidate
            params = parameters(record.with_suffix('.spice').read_text())
            params = {**params, **{k: v for k, f in LEGACY.items() if (v := f(params)) is not None}}
            status = design_memory.classify(data['dc_passed'], spec_check(specs['targets'], data['metrics']))
            points.append((status, data['metrics'], params))
        if ref and points:
            yield ref, design_memory.condition_key(specs), specs['targets'], points


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--circuit', default='opamp')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    base = ROOT / 'circuits' / args.circuit
    refs = load_references(base / 'reference')
    current = json.loads((base / 'specs/target.json').read_text())
    memory, stats = {}, dict(open_loop_skipped=0, runs=0)
    folders = sorted((base / 'results/runs').glob('*')) + [base / 'results']
    for folder in folders:
        if not (folder / 'specs.json').exists():
            continue
        stats['runs'] += 1
        for ref, cond, targets, points in run_points(folder, refs, stats):
            design_memory.add(memory, (args.circuit, ref.id, cond), ref, targets, points)
    for ref in refs.values():
        for point in ref.verified:   # simulated designs quoted by the reference: they met the targets they were found for
            specs = {**current, 'conditions': {**current['conditions'], **point['conditions']}}
            if 'params' in point:
                design_memory.add(memory, (args.circuit, ref.id, design_memory.condition_key(specs)), ref, current['targets'],
                                  [('P', point['metrics'], point['params'])])
        for params in EXTRA_DC_FAILS.get(ref.id, []):
            design_memory.add(memory, (args.circuit, ref.id, design_memory.condition_key(current)), ref, current['targets'],
                              [('D', {}, params)])
    if not args.dry_run:
        design_memory.save(memory)
    print(stats)
    for key, section in sorted(memory.items()):
        kinds = ''.join(sorted(r.status for r in section.rows))
        print(f'{key[1]:<34} {len(section.rows):>3} points  {kinds}   [{key[2]}]')


if __name__ == '__main__':
    main()
