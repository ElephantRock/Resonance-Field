from resonance.experiments.post_crossing_reconvergence_audit import longest_true_run, terminal_recovery


def _series(values):
    return [{"cycle": index, "macro_distance": value} for index, value in enumerate(values)]


def test_longest_true_run():
    assert longest_true_run([False, True, True, False, True]) == 2
    assert longest_true_run([]) == 0


def test_terminal_recovery_without_crossing_is_activation():
    series = _series([0.0] * 12)
    assert terminal_recovery(
        series,
        key="macro_distance",
        threshold=0.05,
        activation_cycle=3,
        hits=3,
        window=5,
        cycles=12,
    ) == 3


def test_terminal_recovery_after_last_persistent_window():
    values = [0.0] * 3 + [0.06, 0.07, 0.0, 0.08, 0.0] + [0.0] * 6
    series = _series(values)
    assert terminal_recovery(
        series,
        key="macro_distance",
        threshold=0.05,
        activation_cycle=3,
        hits=3,
        window=5,
        cycles=len(values),
    ) == 8


def test_terminal_recovery_beyond_horizon():
    values = [0.0] * 3 + [0.1] * 8
    series = _series(values)
    assert terminal_recovery(
        series,
        key="macro_distance",
        threshold=0.05,
        activation_cycle=3,
        hits=3,
        window=5,
        cycles=len(values),
    ) == len(values) + 1
