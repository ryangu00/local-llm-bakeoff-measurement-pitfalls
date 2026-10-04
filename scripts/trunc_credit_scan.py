#!/usr/bin/env python3
"""Scan scored rows for credited truncations; retain the source arithmetic."""
import argparse
import json
from pathlib import Path


def scan(root, pattern='*'):
    for run in sorted(Path(root).glob(pattern)):
        for path in sorted((run / 'raw').glob('*-run*.jsonl')):
            if path.name.endswith('.regraded.jsonl'):
                continue
            rows = []
            for line in path.read_text().splitlines():
                try:
                    rows.append(json.loads(line))
                except (ValueError, TypeError):
                    pass
            rows = [r for r in rows if 'score' in r]
            if not rows:
                continue
            score = lambda r: float(r.get('score') or 0)
            truncated = [r for r in rows if r.get('finish') == 'length']
            credited = [r for r in truncated if score(r) > 0]
            separated = sum(bool((r.get('usage') or {}).get('reasoning')) for r in rows)
            total = sum(map(score, rows))
            yield {'run': run.name, 'file': path.name, 'items': len(rows),
                   'score': 100 * total / len(rows), 'truncated': len(truncated),
                   'credited': len(credited),
                   'without_credit': 100 * (total - sum(map(score, credited))) / len(rows),
                   'separated_reasoning_percent': 100 * separated / len(rows)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('runs_root'); p.add_argument('--glob', default='*')
    a = p.parse_args()
    for row in scan(a.runs_root, a.glob):
        print(json.dumps(row, sort_keys=True))


if __name__ == '__main__':
    main()
