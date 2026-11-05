"""Evidence-based proposal metrics; absence of labels is never a pass.

Source truth must be supplied by an independently checked corpus catalogue.
Keyword presence and merely returning a source are not retrieval ground truth.
"""
from __future__ import annotations

import math
from typing import Any

THRESHOLDS = {
    'top5_hit_rate': .70, 'source_traceability_rate': .80,
    'parameter_extraction_accuracy': .70, 'tool_call_correctness': .80,
    'calculation_correctness': .90, 'visualization_match_rate': .75,
    'anomaly_cause_coverage': .70,
}


def same_value(actual: Any, expected: Any, *, tolerance: float = 1e-6) -> bool:
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        return (isinstance(actual, (int, float)) and not isinstance(actual, bool)
                and math.isfinite(actual) and math.isfinite(expected)
                and math.isclose(actual, expected, rel_tol=tolerance, abs_tol=0.))
    return type(actual) is type(expected) and actual == expected


def source_matches(source: dict, expected: dict) -> bool:
    # An empty marker/title is never sufficient to certify identity.
    keys = [key for key in ('doc_id', 'chunk_id', 'knowledge_unit_id') if expected.get(key) is not None]
    return bool(keys) and all(str(source.get(key)) == str(expected[key]) for key in keys)


def trace_matches(source: dict, checked: dict) -> bool:
    keys = [key for key in ('doc_id', 'chunk_id', 'knowledge_unit_id') if source.get(key) is not None]
    if not keys or not all(checked.get(key) is not None and str(source[key]) == str(checked[key]) for key in keys):
        return False
    for key in ('page_start', 'page_end'):
        if source.get(key) is not None and source[key] != checked.get(key):
            return False
    return checked.get('verified') is True and bool(checked.get('source_locator'))


def case_metrics(case: dict, response: dict, calc: dict, *, source_catalog: list[dict] | None = None) -> dict:
    sources = [s for s in response.get('sources', []) if isinstance(s, dict)]
    parameter_checks = []
    inputs = calc.get('tool_inputs') or {}
    for name, expected in (case.get('expected_parameters') or {}).items():
        # fluid is a parser semantic input, sometimes preserved in tool_inputs;
        # missing input stays a miss rather than being inferred from the query.
        actual = inputs.get('fluid_name' if name == 'fluid' else name)
        parameter_checks.append({'parameter': name, 'expected': expected, 'actual': actual,
                                 'passed': same_value(actual, expected)})
    relevant = case.get('expected_relevant_sources')
    hit = (any(source_matches(s, gold) for s in sources[:5] for gold in relevant)
           if isinstance(relevant, list) and relevant else None)
    traceable = None
    if source_catalog is not None and case.get('requires_sources'):
        # Whole-answer rate: all emitted citations must map to checked corpus
        # entries including a verified location; no citations is a failed case.
        traceable = bool(sources) and all(any(
            trace_matches(s, entry)
            for entry in source_catalog) for s in sources)
    expected_tool = case.get('expected_tool')
    tool_ok = None
    if 'expected_tool' in case:
        ran = calc.get('tool_status') == 'ok' and calc.get('used_calculation') is True
        if expected_tool is None:
            tool_ok = not ran
        elif case.get('expected_missing_parameters'):
            tool_ok = (calc.get('tool_name') == expected_tool and not ran and
                       set(case['expected_missing_parameters']).issubset(calc.get('missing_parameters') or []))
        else:
            tool_ok = calc.get('tool_name') == expected_tool and ran
    # Only explicit machine-readable result labels count; do not grade a graph
    # or cause from free-text keyword overlap.
    metadata = response.get('metadata') or {}
    visualization = metadata.get('visualization') or {}
    template = visualization.get('graph_type') or visualization.get('template_id') if isinstance(visualization, dict) else None
    expected_template = case.get('expected_graph_type') or case.get('expected_template_id')
    graph = visualization.get('graph') or {} if isinstance(visualization, dict) else {}
    generated_graph = (isinstance(graph, dict) and bool(graph.get('nodes')) and bool(graph.get('edges'))
                       and visualization.get('generated') is True)
    expected_causes = case.get('expected_cause_ids')
    anomaly = metadata.get('anomaly_analysis') or {}
    actual_causes = set(anomaly.get('cause_ids') or []) if isinstance(anomaly, dict) else set()
    return {
        'parameter_checks': parameter_checks,
        'top5_hit': hit,
        'source_traceable': traceable,
        'tool_correct': tool_ok,
        'visualization_match': generated_graph and template == expected_template if expected_template else None,
        'cause_hits': len(set(expected_causes) & actual_causes) if expected_causes else None,
        'cause_total': len(set(expected_causes)) if expected_causes else None,
    }


def build_proposal_metrics(results: list[dict]) -> dict:
    samples: dict[str, list[bool]] = {key: [] for key in THRESHOLDS}
    mapping = {'top5_hit_rate': 'top5_hit', 'source_traceability_rate': 'source_traceable',
               'tool_call_correctness': 'tool_correct', 'visualization_match_rate': 'visualization_match'}
    for result in results:
        evidence = result.get('proposal_evidence') or {}
        for metric, key in mapping.items():
            value = evidence.get(key)
            if value is not None: samples[metric].append(bool(value))
        samples['parameter_extraction_accuracy'].extend(bool(c['passed']) for c in evidence.get('parameter_checks', []))
        if result.get('calculation_checks'):
            samples['calculation_correctness'].append(bool(result.get('calculation_passed')))
        if evidence.get('cause_total') is not None:
            samples['anomaly_cause_coverage'].extend([True] * evidence['cause_hits'])
            samples['anomaly_cause_coverage'].extend([False] * (evidence['cause_total'] - evidence['cause_hits']))
    metrics = {}
    for name, threshold in THRESHOLDS.items():
        values = samples[name]
        value = sum(values) / len(values) if values else None
        metrics[name] = {'numerator': sum(values), 'denominator': len(values), 'value': value,
                         'threshold': threshold, 'status': 'unavailable' if value is None else ('met' if value >= threshold else 'not_met')}
    return metrics
