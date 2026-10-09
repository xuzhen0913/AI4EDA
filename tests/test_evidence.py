from analog_agents.evidence import device_table, measurement_summary, node_voltages, outcome, residual_log, sig

M = dict(analysis_mode='dc', simulation_valid=True, dc_passed=False, metrics={'power_w': 1.23456789e-4, 'ugb_hz': None},
         checks={'power_w': True, 'ugb_hz': None}, errors=[], warnings=['warning: x'], ac_polarity={'passed': None},
         dc_operating_point={'v(out)': 1.69740127, 'v(n1)': 0.7340233, '@m.xm1.m[id]': 1e-5},
         dc_acceptance=dict(failed_devices=['XM7'], devices={
             'XM1': dict(passed=True, checks=dict(conducting=True, saturation=True), id_a=2e-5, vgs_or_vsg_v=.7123456,
                         vds_or_vsd_v=.5, vth_magnitude_v=.6, vdsat_magnitude_v=.1, overdrive_v=.11, saturation_margin_v=.4),
             'XM7': dict(passed=False, checks=dict(conducting=True, saturation=False), id_a=2e-5, vgs_or_vsg_v=1.07,
                         vds_or_vsd_v=.1, vth_magnitude_v=1.0, vdsat_magnitude_v=.117, overdrive_v=.067, saturation_margin_v=-.014),
             'XM9': dict(passed=False, reason='Missing or nonfinite DC diagnostics')}))


def test_one_merged_device_table_replaces_three_overlapping_ones():
    table = device_table(M, {'XM1': 'nfet', 'XM7': 'pfet'}, {'XM1': dict(W_over_L=20, gm_uS=190, gm_over_id_per_V=9.5, gm_over_gds=95)})
    cols = table['columns']
    rows = {r[0]: dict(zip(cols, r)) for r in table['rows']}
    assert rows['XM1']['gm_uS'] == 190 and rows['XM1']['Id_uA'] == 20 and rows['XM1']['failed_checks'] == ''
    assert rows['XM7']['failed_checks'] == 'saturation' and rows['XM7']['gm_uS'] is None
    assert rows['XM9']['failed_checks'] == 'Missing or nonfinite DC diagnostics' and rows['XM9']['Id_uA'] is None
    assert len(cols) == len(table['rows'][0])


def test_summary_nodes_and_rounding():
    s = measurement_summary(M)
    assert s['metrics'] == {'power_w': 0.00012346, 'ugb_hz': None} and s['failed_metrics'] == [] and 'failed_dc_devices' not in s
    assert 'metrics' not in measurement_summary(M, metrics=False)
    assert 'errors' not in s and s['warnings'] == ['warning: x']
    assert node_voltages(M) == {'out': 1.6974, 'n1': 0.73402}
    assert sig(0) == 0 and sig(None) is None and sig(123456.789) == 123460.0
    assert outcome(dict(dc_passed=True, failed_dc_devices=[], metrics={'a': 1.23456789}, simulation_number=3)) == \
        dict(dc_passed=True, failed_dc_devices=[], metrics={'a': 1.2346})


def test_residual_log_keeps_only_information_not_in_structured_fields():
    log = '\n'.join(['COMMAND: ["x"]', 'Note: No compatibility mode selected!', 'Circuit: * t', 'v(out) = 1.5', 'DEVICE_xm1',
                     'warning: x', 'doAnalyses: weird convergence message', 'END_DC_OPERATING_POINT', 'RETURN_CODE: 0'])
    assert residual_log(log, M) == 'doAnalyses: weird convergence message'
