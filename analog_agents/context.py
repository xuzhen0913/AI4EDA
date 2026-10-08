"""Deterministic, topology-independent packing; original experiment files stay intact."""
import copy
import hashlib
import json
import math
import re


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


PARAM = re.compile(r'^(\.param\s+)(\w+)(\s*=\s*)(\S+)(.*)$', re.M | re.I)
SCALAR = re.compile(r'^\s*([^\s=]+)\s*=\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)(?:\s*)$')


def pack_netlist(text):
    # Keep all circuit statements, formulas and substantive constraint comments.
    return '\n'.join(line.rstrip() for line in text.splitlines()
                     if line.strip() and not re.fullmatch(r'\s*\*\s*[-=*_ ]*', line))


def pack_history(history):
    rows=[]
    previous=None
    previous_row=None
    for original in history:
        row=copy.deepcopy(original)
        before=row.pop('parameters_before', None)
        after=row.pop('parameters_after', None)
        if before is not None:
            if previous is None:
                row['parameters_before']=before
            else:
                row['parameters_before_delta']={k:v for k,v in before.items() if previous.get(k)!=v}
                removed=sorted(set(previous)-set(before))
                if removed:row['parameters_before_removed']=removed
        if after is not None:
            if before is None:row['parameters_after']=after
            else:
                row['actual_parameter_delta']={k:v for k,v in after.items() if before.get(k)!=v}
                removed=sorted(set(before)-set(after))
                if removed:row['parameters_after_removed']=removed
            previous=after
        else:previous=before
        # Preserve EVERY measured outcome, rejection, proposed value and status.
        # Old generated prose is not evidence and can repeat incorrect physics.
        for key in ('qwen_analysis','analysis','model_analysis'):
            row.pop(key,None)
        row['parameter_changes']=[{k:v for k,v in c.items() if k!='reason'}
                                  for c in row.get('parameter_changes',[])]
        for key in ('qwen_token_usage','token_usage','iteration_time'):
            row.pop(key,None)
        if (previous_row is not None and 'result_measurements' in previous_row
                and 'measurements' in row and row['measurements']==previous_row['result_measurements']
                and 'iteration' in previous_row):
            row.pop('measurements')
            row['measurements_from_iteration']=previous_row['iteration']
        rows.append(row)
        previous_row=original
    return rows


def compact_payload(payload, record):
    """Only pack the recognized sizing envelope; other agents keep their payload."""
    if not {'reference_spice','candidate_spice','measurements','full_ngspice_log','history'} <= payload.keys():
        return payload
    packed=copy.deepcopy(payload)
    packed['input_scope']='Only this optimization invocation; history contains iterations since its fresh start, not prior GPU/model runs.'
    packed['measurements'].pop('log',None)
    ref=payload['reference_spice'];candidate=payload['candidate_spice']
    shape=lambda text:PARAM.sub(lambda m:m[1]+m[2]+m[3]+'<SCALAR>'+m[5],text)
    ref_pairs=[(m[2],m[4]) for m in PARAM.finditer(ref)]
    cur_pairs=[(m[2],m[4]) for m in PARAM.finditer(candidate)]
    if (shape(ref)==shape(candidate) and len(dict(ref_pairs))==len(ref_pairs)
            and len(dict(cur_pairs))==len(cur_pairs)):
        packed.pop('candidate_spice')
        if packed.get('current_parameters')==dict(cur_pairs):
            packed['candidate_encoding']='Reference with .param values replaced by current_parameters; all other text identical. Use current_parameters for old_value.'
        else:
            packed['candidate_parameter_overrides']={k:v for k,v in cur_pairs if dict(ref_pairs).get(k)!=v}
            packed['candidate_encoding']='Reference with ONLY candidate_parameter_overrides applied; all other text identical.'
    else:
        # Never hide a topology/expression change behind a parameter-only encoding.
        packed['candidate_spice']=pack_netlist(candidate)
    packed['reference_spice']=pack_netlist(ref)
    measurements=payload['measurements']
    known={k.lower():v for section in ('dc_operating_point','metrics')
           for k,v in measurements.get(section,{}).items()}
    retained=[];removed=0
    for line in payload['full_ngspice_log'].splitlines():
        # Launcher command exposes the archive directory but is not circuit evidence.
        if line.startswith('COMMAND: '):
            continue
        match=SCALAR.fullmatch(line)
        if match:
            value=known.get(match[1].lower())
            # Exact parsed numeric equality only: changed/repeated values stay visible.
            if isinstance(value,(int,float)) and math.isfinite(value) and float(match[2])==value:
                removed+=1
                continue
        if line.strip():retained.append(line)
    packed.pop('full_ngspice_log')
    packed['log_additional_evidence']='\n'.join(retained)
    # Lossless factoring of long device prefixes; keep signed raw OP values.
    op=packed['measurements'].get('dc_operating_point',{})
    devices={};other={}
    for key,value in op.items():
        match=re.fullmatch(r'(@[^\[]+)\[([^\]]+)\]',key)
        if match:devices.setdefault(match[1],{})[match[2]]=value
        else:other[key]=value
    if devices:
        packed['measurements']['dc_operating_point']=other
        packed['measurements']['device_operating_point']=devices
    packed['history']=pack_history(payload['history'])
    # Keep every numeric DC result, but avoid repeating field names for each device.
    dc=packed['measurements'].get('dc_acceptance',{})
    details=dc.get('devices',{})
    if details:
        columns=list(dict.fromkeys(k for values in details.values() for k in values))
        dc['device_table']={'columns':['device']+columns,
                           'rows':[[name]+[values.get(k) for k in columns] for name,values in details.items()]}
        dc.pop('devices')
    # The simulator's failure labels are authoritative, not historical model prose.
    packed['decision_focus']={
        'failed_dc_checks':{name:{'failed_checks':[k for k,v in d.get('checks',{}).items() if v is False],
                                  **({'reason':d['reason']} if 'reason' in d else {})}
                            for name,d in details.items() if not d.get('passed',False)},
        'failed_performance_metrics':[k for k,v in measurements.get('checks',{}).items() if v is False],
        'unmeasured_metrics':[k for k,v in measurements.get('metrics',{}).items() if v is None]}

    packed['context_encoding']=(
        'Reference constraints/formulas, global rules, targets and current measurements retained. '
        'device_operating_point maps raw device prefix to property/value; expand as prefix[property]. '
        'Duplicate scalar log lines and launcher COMMAND/path metadata are omitted; simulator diagnostics/errors/warnings remain. '
        'History retains every iteration/outcome/rejection; start from first parameters_before, then apply before_delta/removals and actual_parameter_delta/removals sequentially. '
        'Before deltas use previous iteration AFTER values; measurements_from_iteration references that iteration result_measurements. Proposed changes need not be accepted. '
        'dc_acceptance.device_table rows follow columns, including exact checks and margins. Missing heterogeneous fields use null. '
        'History omits model prose and token/time metadata; all proposal values and outcomes remain. '
        'Model explanations are hypotheses, not physical facts. No original on-disk evidence is modified.')
    before=dumps(payload);after=dumps(packed)
    record['context_compression']={
        'version':2,'original_json_chars':len(before),'packed_json_chars':len(after),
        'source_payload_sha256':hashlib.sha256(before.encode()).hexdigest(),
        'packed_payload_sha256':hashlib.sha256(after.encode()).hexdigest(),
        'history_iterations_retained':len(payload['history']),
        'duplicate_log_assignments_removed':removed,
        'candidate_encoded_as_parameters':'candidate_spice' not in packed}
    return packed
