#!/usr/bin/env python3
"""Compare the recorded arm, identity and grader; never infer missing identity."""
import argparse
import json
from pathlib import Path

FIELDS = ['bank_hash', 'grader_version', 'recipe_arm', 'sampling', 'chat_template_kwargs',
          'max_tokens', 'system', 'thinking', 'served_identity', 'grader_env']


def check(a, b, intentional=()):
    unknown = set(intentional) - set(FIELDS)
    if unknown:
        raise ValueError('unknown intentional fields: ' + ', '.join(sorted(unknown)))
    missing = [k for k in FIELDS if k not in a or k not in b or a[k] is None or b[k] is None]
    for k in ('bank_hash', 'grader_version', 'recipe_arm', 'served_identity', 'grader_env'):
        if not a.get(k) or not b.get(k):
            missing.append(k)
    diffs = {k: [a.get(k), b.get(k)] for k in FIELDS if a.get(k) != b.get(k)}
    blocking = {k: v for k, v in diffs.items() if k not in intentional}
    notes = [f'intentional difference: {k}' for k in diffs if k in intentional]
    return {'ok': not missing and not blocking, 'differences': diffs, 'blocking': blocking,
            'missing': sorted(set(missing)), 'notes': notes}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('a'); p.add_argument('b')
    p.add_argument('--intentional', action='append', default=[], choices=FIELDS)
    a = p.parse_args()
    out = check(json.loads(Path(a.a).read_text()), json.loads(Path(a.b).read_text()), a.intentional)
    print(json.dumps(out, indent=2)); return 0 if out['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
