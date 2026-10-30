from person_source_boundaries import holding_snapshot_explanation_errors


def holdings(periods=('', '')):
    return [{'source_url': f'https://fixture.invalid/{index}', 'fact': f'林知远持股{value}%。',
        'observation': {'period': period, 'metrics': [{'metric': 'holding_ratio'}]}}
        for index, (value, period) in enumerate(zip((35, 42), periods))]


def test_unknown_holding_dates_do_not_prove_the_reason_for_conflicting_numbers():
    assert holding_snapshot_explanation_errors('持股35%与42%，基准日未明，均属不同时点口径。', holdings()) == [
        'undated_holdings_explained_as_different_snapshots']


def test_explicit_snapshot_periods_or_uncertainty_do_not_trigger_this_narrow_guard():
    assert not holding_snapshot_explanation_errors('持股35%与42%，均属不同时点口径。', holdings(('2020-12-31', '2022-12-31')))
    assert not holding_snapshot_explanation_errors('持股35%与42%，不能认定均属不同时点口径。', holdings())
    assert not holding_snapshot_explanation_errors('持股35%与42%，可能是不同时点数据，仍待核对。', holdings())
    assert not holding_snapshot_explanation_errors('持股35%与42%，基准日未明，保留冲突，不合并。', holdings())
