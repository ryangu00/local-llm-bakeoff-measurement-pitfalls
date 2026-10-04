#!/usr/bin/env python3
"""Historical nominal-denominator TTFT probe; prompts repeat across invocations."""
import argparse
import json
import os
import random
import statistics
import time
import urllib.request

WORDS = 'alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike november oscar papa quebec romeo sierra tango'.split()


def prompt(n, i):
    rng = random.Random(n * 1000 + i)
    return ' '.join(rng.choice(WORDS) for _ in range(int(n / 1.3)))


def first_real_chunk(lines, start, clock=time.monotonic):
    for raw in lines:
        line = raw.decode().strip() if isinstance(raw, bytes) else raw.strip()
        if not line.startswith('data:'):
            continue
        if line[5:].strip() == '[DONE]':
            break
        data = json.loads(line[5:])
        if data.get('model') == 'keepalive':
            continue
        delta = (data.get('choices') or [{}])[0].get('delta') or {}
        if delta.get('content') or delta.get('reasoning_content'):
            return clock() - start, data
    raise ValueError('stream ended without a content or reasoning token')


def measure(url, model, text, key=''):
    body = {'model': model, 'messages': [{'role': 'user', 'content': text}],
            'max_tokens': 1, 'temperature': 0, 'stream': True}
    headers = {'Content-Type': 'application/json'}
    if key:
        headers['Authorization'] = 'Bearer ' + key
    req = urllib.request.Request(url, json.dumps(body).encode(), headers)
    start = time.monotonic()
    with urllib.request.urlopen(req, timeout=300) as response:
        return first_real_chunk(response, start)[0]


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base-url', required=True); p.add_argument('--model', required=True)
    p.add_argument('--api-key-env', default=''); p.add_argument('--tiers', default='1000,4000,16000,64000')
    a = p.parse_args()
    key = os.environ.get(a.api_key_env, '') if a.api_key_env else ''
    for n in map(int, a.tiers.split(',')):
        passes = [measure(a.base_url.rstrip('/') + '/chat/completions', a.model, prompt(n, i), key) for i in range(1, 5)]
        median = statistics.median(passes[1:])
        print(json.dumps({'nominal_tier': n, 'ttft_median': median, 'retained_passes': passes[1:],
                          'nominal_tokens_per_second': n / median,
                          'warning': 'nominal denominator; repeated invocation can reuse cached prompts'}))
