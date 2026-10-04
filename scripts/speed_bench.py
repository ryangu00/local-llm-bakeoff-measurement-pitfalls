#!/usr/bin/env python3
"""Non-streaming decode, concurrency and prefill; usage counts and fresh prompts."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import random
import statistics
import time
import urllib.request
import uuid

WORDS = ('alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike '
         'november oscar papa quebec romeo sierra tango uniform victor whiskey xray').split()
SAMPLING = {'temperature': 0.6, 'top_p': 0.95}


def call(base, model, key, content, max_tokens, timeout=900, sampling=None, fresh=True, nonce=''):
    if fresh:
        content = f'[run {nonce}{uuid.uuid4().hex}] {content}'
    body = {'model': model, 'messages': [{'role': 'user', 'content': content}],
            'max_tokens': max_tokens, 'stream': False, **(sampling or SAMPLING)}
    headers = {'Content-Type': 'application/json'}
    if key:
        headers['Authorization'] = 'Bearer ' + key
    request = urllib.request.Request(base.rstrip('/') + '/chat/completions', json.dumps(body).encode(), headers)
    start = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.load(response)
    elapsed = time.perf_counter() - start
    usage = data.get('usage') or {}
    if any(not isinstance(usage.get(k), int) or usage[k] <= 0 for k in ('prompt_tokens', 'completion_tokens')):
        raise ValueError('positive server usage counts required')
    choice = data['choices'][0]
    message = choice.get('message') or {}
    return {'secs': elapsed, 'prompt': usage['prompt_tokens'], 'completion': usage['completion_tokens'],
            'finish': choice.get('finish_reason'), 'raw_usage': usage, 'text': message.get('content') or '',
            'reasoning': message.get('reasoning_content') or message.get('reasoning') or ''}


def essay(i):
    topics = ['the history of cartography', 'how bridges carry load', 'the chemistry of bread',
              'the evolution of written numerals', 'ocean currents and climate', 'the design of railway timetables',
              'how compilers optimize loops', 'the migration of birds', 'the economics of lighthouses']
    return f'Write a long, detailed essay (at least 1500 words) about {topics[i % len(topics)]}. Variant {i}.'


def filler(n, seed):
    rng = random.Random(seed)
    return ' '.join(rng.choice(WORDS) for _ in range(int(n / 1.3))) + '\n\nReply with exactly one word: done.'


def med_drop_first(values):
    if len(values) < 2:
        raise ValueError('at least two passes required')
    return statistics.median(values[1:])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base-url', required=True); p.add_argument('--model', required=True)
    p.add_argument('--label', required=True); p.add_argument('--api-key-env', default='')
    p.add_argument('--out', default='.'); p.add_argument('--runs', type=int, default=4)
    p.add_argument('--decode-tokens', type=int, default=512); p.add_argument('--conc', default='4,8')
    p.add_argument('--prefill', default='1000,4000,16000,64000')
    p.add_argument('--nonce', default='', help='Optional prefix; each measurement also gets a unique suffix')
    p.add_argument('--greedy', type=int, default=0); p.add_argument('--greedy-tokens', type=int, default=512)
    p.add_argument('--greedy-only', action='store_true')
    a = p.parse_args()
    if a.runs < 2 and not a.greedy_only:
        p.error('--runs must allow dropping the first pass')
    if Path(a.label).name != a.label or a.label in ('.', '..'):
        p.error('--label must be a filename component')
    key = os.environ.get(a.api_key_env, '') if a.api_key_env else ''
    send = lambda text, cap: call(a.base_url, a.model, key, text, cap, nonce=a.nonce)
    result = {'label': a.label, 'model': a.model, 'sampling': SAMPLING, 'base_url': a.base_url,
              'ts': time.strftime('%F %T'), 'decode': {}, 'concurrency': {}, 'prefill': {}}
    if not a.greedy_only:
        runs = []
        for i in range(a.runs):
            r = send(essay(i), a.decode_tokens)
            r['tps'] = r['completion'] / r['secs']; runs.append(r)
            print(f"decode: {r['completion']} / {r['secs']:.6f} = {r['tps']:.6f} tok/s")
        result['decode'] = {'median_tps': med_drop_first([r['tps'] for r in runs]), 'runs': runs,
                            'all_length': all(r['finish'] == 'length' for r in runs)}
        for n in [int(x) for x in a.conc.split(',') if x]:
            runs = []
            for k in range(a.runs):
                start = time.perf_counter()
                with ThreadPoolExecutor(n) as pool:
                    rows = list(pool.map(lambda j: send(essay(100 * n + 10 * k + j), 256), range(n)))
                wall = time.perf_counter() - start
                tokens = sum(r['completion'] for r in rows)
                runs.append({'wall': wall, 'tokens': tokens, 'agg_tps': tokens / wall,
                             'max_req_secs': max(r['secs'] for r in rows)})
            result['concurrency'][n] = {'median_agg_tps': med_drop_first([r['agg_tps'] for r in runs]), 'runs': runs}
        for n in [int(x) for x in a.prefill.split(',') if x]:
            runs = []
            for k in range(a.runs):
                r = send(filler(n, n * 1000 + k), 1)
                r['prefill_tps'] = r['prompt'] / r['secs']; runs.append(r)
                print(f"prefill: {r['prompt']} / {r['secs']:.6f} = {r['prefill_tps']:.6f} tok/s")
            result['prefill'][n] = {'median_secs': med_drop_first([r['secs'] for r in runs]),
                                    'median_prompt_tokens': med_drop_first([r['prompt'] for r in runs]),
                                    'median_tps': med_drop_first([r['prefill_tps'] for r in runs]), 'runs': runs}
    if a.greedy:
        result['greedy'] = []
        for i in range(a.greedy):
            r = call(a.base_url, a.model, key, essay(1000 + i), a.greedy_tokens,
                     sampling={'temperature': 0, 'top_p': 1}, fresh=False)
            result['greedy'].append({'i': i, **{k: r[k] for k in ('completion', 'finish', 'text', 'reasoning')}})
    Path(a.out).mkdir(parents=True, exist_ok=True)
    destination = Path(a.out) / (a.label + '.json')
    destination.write_text(json.dumps(result, indent=2) + '\n')
    print('saved ' + str(destination))


if __name__ == '__main__':
    main()
