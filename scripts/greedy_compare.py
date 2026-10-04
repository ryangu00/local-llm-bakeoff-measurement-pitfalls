#!/usr/bin/env python3
"""Compare full reasoning plus content; an empty side is an invalid test."""
import argparse
import json
from pathlib import Path


def compare(a, b):
    if not a or not b or len(a) != len(b):
        return {'verdict': 'invalid', 'reason': 'missing or unequal sample lists', 'rows': []}
    rows = []
    for x, y in zip(a, b):
        full = lambda g: f"{g.get('reasoning') or ''}\n<<CONTENT>>\n{g.get('text') or ''}"
        if not (x.get('reasoning') or x.get('text')) or not (y.get('reasoning') or y.get('text')):
            rows.append({'verdict': 'invalid', 'reason': 'empty output'})
            continue
        fx, fy = full(x), full(y)
        if fx == fy:
            rows.append({'verdict': 'identical'})
        else:
            k = next((i for i, (p, q) in enumerate(zip(fx, fy)) if p != q), min(len(fx), len(fy)))
            rows.append({'verdict': 'different', 'first_divergence': k})
    verdict = ('invalid' if any(r['verdict'] == 'invalid' for r in rows) else
               'identical' if all(r['verdict'] == 'identical' for r in rows) else 'different')
    return {'verdict': verdict, 'rows': rows}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('a'); p.add_argument('b'); a = p.parse_args()
    out = compare(json.loads(Path(a.a).read_text())['greedy'], json.loads(Path(a.b).read_text())['greedy'])
    print(json.dumps(out)); return {'identical': 0, 'different': 1, 'invalid': 2}[out['verdict']]


if __name__ == '__main__':
    raise SystemExit(main())
