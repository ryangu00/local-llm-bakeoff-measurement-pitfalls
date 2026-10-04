#!/usr/bin/env python3
"""Summarize run errors, truncations and revoked credit; do not regrade."""
import argparse
import json
from pathlib import Path


def summarize(directory):
    directory = Path(directory)
    rows, bad = [], []
    for path in sorted((directory / 'raw').glob('*.jsonl')):
        if path.name.endswith('.regraded.jsonl'):
            continue
        data = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        rec = {'file': path.name, 'items': len(data),
               'errors': sum(bool(r.get('error')) for r in data),
               'truncated': sum(r.get('finish') == 'length' for r in data),
               'credit_revoked': sum(isinstance(r.get('detail'), dict) and
                                    'truncated_credit_revoked' in r['detail'] for r in data)}
        rows.append(rec)
        if rec['errors']:
            bad.append(path.name)
    for path in sorted((directory / 'raw').glob('*.json')):
        try:
            data = json.loads(path.read_text())
        except ValueError:
            rows.append({'file': path.name, 'parse_error': True}); bad.append(path.name)
            continue
        text = json.dumps(data)
        rate = data.get('config', {}).get('error_rate') if isinstance(data, dict) else None
        rows.append({'file': path.name, 'error_rate': rate, 'markup_remaining': text.count('DSML'),
                     'missing_step': text.count('missing_step')})
        if rate:
            bad.append(path.name)
    result = json.loads((directory / 'results.json').read_text())
    return {'categories': rows, 'categories_with_errors': bad,
            'recorded_scores': [{'cat': r['cat'], 'median': r.get('median')} for r in result['rows']]}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('run_dir'); a = p.parse_args()
    print(json.dumps(summarize(a.run_dir), indent=2))
