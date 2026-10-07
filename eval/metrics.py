"""Pure metric calculations. Every expected episode stays in every rate denominator."""
import math
from collections import Counter

GATE_CLASSES = ('gate_permit', 'gate_block')
SEMANTIC_CLASSES = ('match', 'mismatch', 'unknown')
NON_DECISIONS = ('abstain', 'invalid', 'no_output')


def ratio(numerator: int, denominator: int) -> dict:
    return {'numerator': numerator, 'denominator': denominator,
            'value': numerator / denominator if denominator else None}


def classification(expected: list[str], predicted: list[str], classes: tuple[str, ...]) -> dict:
    if len(expected) != len(predicted):
        raise ValueError('prediction length mismatch')
    if any(value not in classes for value in expected):
        raise ValueError('unknown expected class')
    if any(value not in classes + NON_DECISIONS for value in predicted):
        raise ValueError('unknown predicted class')
    matrix = {truth: {prediction: 0 for prediction in classes + NON_DECISIONS} for truth in classes}
    for truth, prediction in zip(expected, predicted):
        matrix[truth][prediction] += 1
    per_class = {}
    for name in classes:
        tp = matrix[name][name]
        support = sum(matrix[name].values())
        predicted_count = sum(matrix[truth][name] for truth in classes)
        fp, fn = predicted_count - tp, support - tp
        per_class[name] = {'support': support, 'tp': tp, 'fp': fp, 'fn': fn,
                           'precision': ratio(tp, tp + fp), 'recall': ratio(tp, tp + fn),
                           'f1': ratio(2 * tp, 2 * tp + fp + fn)}
    supported = [row for row in per_class.values() if row['support']]
    correct = sum(matrix[name][name] for name in classes)
    decisive = sum(p in classes for p in predicted)
    n = len(expected)
    return {'n_expected': n, 'confusion_matrix': matrix, 'per_class': per_class,
            'accuracy_all_episodes': ratio(correct, n),
            'decision_coverage': ratio(decisive, n),
            'accuracy_on_decisions': ratio(correct, decisive),
            'macro_f1_supported_classes': {
                'value': sum(row['f1']['value'] for row in supported) / len(supported) if supported else None,
                'denominator_classes': len(supported)},
            'abstention_rate': ratio(predicted.count('abstain'), n),
            'invalid_output_rate': ratio(predicted.count('invalid'), n),
            'no_output_rate': ratio(predicted.count('no_output'), n)}


def nearest_rank(values: list[float], percentile: float) -> float | None:
    if not 0 < percentile <= 1:
        raise ValueError('percentile outside (0, 1]')
    if not values:
        return None
    if any(type(v) not in (float, int) or not math.isfinite(v) or v < 0 for v in values):
        raise ValueError('nonnegative finite latency required')
    return sorted(values)[math.ceil(percentile * len(values)) - 1]


def score(labels: list[dict], predictions: list[dict]) -> dict:
    """Missing rows are no_output; malformed rows are invalid, never silently dropped.

    Duplicate or foreign case IDs are rejected rather than picking a flattering
    row. This evaluator measures mandatory permission, not production acceptance.
    """
    expected_ids = [row['case_id'] for row in labels]
    if len(set(expected_ids)) != len(expected_ids):
        raise ValueError('duplicate label case_id')
    for label in labels:
        if label['gate_decision'] not in GATE_CLASSES or label['semantic_decision'] not in SEMANTIC_CLASSES:
            raise ValueError('invalid label class')
        if type(label['critical_gate_block']) is not bool:
            raise ValueError('critical flag must be boolean')
        if label['critical_gate_block'] and label['gate_decision'] != 'gate_block':
            raise ValueError('critical false-accept denominator must contain blocked cases only')
    by_id = {}
    for prediction in predictions:
        case_id = prediction.get('case_id')
        if case_id not in expected_ids or case_id in by_id:
            raise ValueError('foreign or duplicate prediction case_id')
        by_id[case_id] = prediction
    gate_predictions, semantic_predictions = [], []
    latency, fallbacks, unknown_fallbacks, modes = [], 0, 0, Counter()
    critical_total, critical_false_accepts, critical_cases = 0, 0, []
    failures = []
    for label in labels:
        prediction = by_id.get(label['case_id'])
        if prediction is None:
            gate = semantic = 'no_output'
            unknown_fallbacks += 1
        else:
            gate = prediction.get('gate_decision')
            semantic = prediction.get('semantic_decision')
            fallback = prediction.get('fallback')
            duration = prediction.get('latency_ms')
            valid = (gate in GATE_CLASSES + NON_DECISIONS and semantic in SEMANTIC_CLASSES + NON_DECISIONS
                     and (fallback is None or type(fallback) is bool)
                     and type(duration) in (int, float) and math.isfinite(duration) and duration >= 0)
            if not valid:
                gate = semantic = 'invalid'
                unknown_fallbacks += 1
            else:
                latency.append(duration)
                fallbacks += fallback is True
                unknown_fallbacks += fallback is None
                modes[str(prediction.get('mode'))] += 1
        gate_predictions.append(gate)
        semantic_predictions.append(semantic)
        if gate != label['gate_decision']:
            failures.append({'case_id': label['case_id'], 'expected': label['gate_decision'], 'actual': gate})
        if label['critical_gate_block']:
            critical_total += 1
            # A malformed telemetry row must not hide an emitted unsafe permit.
            if prediction is not None and prediction.get('gate_decision') == 'gate_permit':
                critical_false_accepts += 1
                critical_cases.append(label['case_id'])
    n = len(labels)
    return {
        'mandatory_gates': classification([r['gate_decision'] for r in labels], gate_predictions, GATE_CLASSES),
        'text_semantics': classification([r['semantic_decision'] for r in labels], semantic_predictions, SEMANTIC_CLASSES),
        'critical_false_accept_rate': ratio(critical_false_accepts, critical_total),
        'critical_false_accept_case_ids': critical_cases,
        'gate_disagreements': failures,
        'fallback_rate': ratio(fallbacks, n),
        'fallback_status_unknown_rate': ratio(unknown_fallbacks, n),
        'mode_counts': dict(modes),
        'latency_ms': {'p50': nearest_rank(latency, .50), 'p95': nearest_rank(latency, .95),
                       'observed_episodes': len(latency), 'expected_episodes': n,
                       'method': 'nearest_rank; input_decode_and_rules_in_process; excludes_process_startup'},
        'fixture_gate_expectations': 'PASS' if n and not failures else 'FAIL',
    }
