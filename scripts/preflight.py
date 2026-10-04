#!/usr/bin/env python3
"""Wall-clock HTTP checks and a synthetic-friendly usability gate."""
import argparse
import json
import math
import os
from pathlib import Path
import statistics
import threading
import time
import urllib.error
import urllib.request

P90_DEFAULT = 30.0
USABILITY_CATS = ['c1-kbqa', 'c4-code', 'c5-extract', 'c7-zhif', 'c10-sre-ops']


def _post(url, payload, key, timeout):
    headers = {'Content-Type': 'application/json'}
    if key:
        headers['Authorization'] = 'Bearer ' + key
    request = urllib.request.Request(url, json.dumps(payload).encode(), headers)
    start = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.load(response)
        if not isinstance(data, dict) or not data.get('choices'):
            return {'ok': False, 'secs': time.monotonic() - start, 'err': 'response has no choices'}
        return {'ok': True, 'secs': time.monotonic() - start, 'resp': data}
    except urllib.error.HTTPError as error:
        try:
            return {'ok': False, 'secs': time.monotonic() - start, 'http': error.code,
                    'body': error.read().decode(errors='replace')[:400]}
        finally:
            error.close()
    except Exception as error:
        return {'ok': False, 'secs': time.monotonic() - start, 'err': type(error).__name__}


def post(url, payload, timeout=900, key=''):
    """The server may keep running after this daemon-thread deadline returns."""
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('timeout must be finite and positive')
    box = {}
    thread = threading.Thread(target=lambda: box.update(result=_post(url, payload, key, timeout)), daemon=True)
    thread.start(); thread.join(timeout)
    return box.get('result', {'ok': False, 'secs': timeout, 'deadline': True,
                              'err': 'wall-clock deadline; server may still be working'})


def validate_threshold(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value <= 0:
        raise ValueError('p90 threshold must be finite and positive')
    return value


def tool_check(response):
    try:
        calls = response['choices'][0]['message'].get('tool_calls')
        return isinstance(calls, list) and any(isinstance(c, dict) and
                    isinstance(c.get('function'), dict) and c['function'].get('name') for c in calls)
    except (KeyError, TypeError, IndexError):
        return False


def image_check(text_response, image_response):
    """Token growth detects dropped images; it does not prove image understanding."""
    try:
        before, after = (r['usage']['prompt_tokens'] for r in (text_response, image_response))
        return all(isinstance(n, int) and not isinstance(n, bool) and n >= 0 for n in (before, after)) and after > before
    except (KeyError, TypeError):
        return False


def usability(post_fn, model, recipe, bank, p90_max=P90_DEFAULT, timeout=None, p90_max_reason=''):
    validate_threshold(p90_max)
    timeout = max(120, 4 * p90_max) if timeout is None else timeout
    req = ({**recipe['sampling'], 'chat_template_kwargs': recipe.get('chat_kwargs', {}),
            'max_tokens': recipe.get('max_tokens', 8000)} if recipe else
           {'temperature': 0.5, 'top_p': 0.95, 'max_tokens': 8000,
            'chat_template_kwargs': {'thinking': True, 'reasoning_effort': 'high'}})
    system = [{'role': 'system', 'content': recipe['system']}] if recipe and recipe.get('system') else []
    rows = []
    for category in USABILITY_CATS:
        item = bank[category][0]
        result = post_fn({'model': model, 'messages': system + [{'role': 'user', 'content': item['prompt']}], **req}, timeout)
        usage = (result.get('resp') or {}).get('usage') or {}
        rows.append({'category': category, 'ok': result['ok'],
                     'secs': timeout if result.get('deadline') else result['secs'],
                     'out_tokens': usage.get('completion_tokens'),
                     'deadline': bool(result.get('deadline'))})
    seconds = [r['secs'] for r in rows]
    p90 = round(statistics.quantiles(seconds, n=10, method='inclusive')[-1], 2)
    errors = sum(not r['ok'] and not r['deadline'] for r in rows)
    tokens = [r['out_tokens'] for r in rows if r['out_tokens'] is not None]
    return {'status': 'ERROR' if errors else 'NOT_INTERACTIVE' if p90 > p90_max else 'INTERACTIVE',
            'median_secs': statistics.median(seconds), 'p90_secs': p90, 'p90_max': p90_max,
            'p90_max_reason': p90_max_reason.strip(), 'errors': errors, 'items': rows,
            'median_out_tokens': statistics.median(tokens) if tokens else None, 'recipe': bool(recipe)}


def usability_gate(measurement, offline=''):
    u = measurement or {}
    status = u.get('status', 'UNMEASURED')
    threshold = validate_threshold(u.get('p90_max', P90_DEFAULT))
    reason = u.get('p90_max_reason', '').strip()
    loose = threshold > P90_DEFAULT and not reason
    if status == 'INTERACTIVE' and not loose:
        return {'ok': True, 'status': status, 'why': reason or 'within interactive threshold'}
    why = 'loosened threshold needs a reason' if loose else status
    if offline.strip():
        return {'ok': True, 'status': status, 'why': why, 'offline': offline.strip()}
    return {'ok': False, 'status': status, 'why': why}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base-url', default='http://127.0.0.1:8000/v1')
    p.add_argument('--model', default='synthetic-model'); p.add_argument('--api-key-env', default='')
    p.add_argument('--bank', default='fixtures/bank.json'); p.add_argument('--recipe')
    p.add_argument('--usability', action='store_true'); p.add_argument('--p90-max', type=float, default=P90_DEFAULT)
    p.add_argument('--p90-max-reason', default=''); p.add_argument('--offline', default='')
    p.add_argument('--tool-payload'); p.add_argument('--image-payload')
    a = p.parse_args(); validate_threshold(a.p90_max)
    key = os.environ.get(a.api_key_env, '') if a.api_key_env else ''
    send = lambda payload, timeout=900: post(a.base_url.rstrip('/') + '/chat/completions', payload, timeout, key)
    base = {'model': a.model, 'messages': [{'role': 'user', 'content': 'Reply with one word: ok'}], 'max_tokens': 64}
    real = send(base)
    out = {'generation': real, 'pass': real['ok'], 'timed_out': bool(real.get('deadline'))}
    for flag, checker in (('tool_payload', tool_check), ('image_payload', image_check)):
        if getattr(a, flag):
            result = send({**base, **json.loads(Path(getattr(a, flag)).read_text())})
            ok = result['ok'] and (checker(result['resp']) if flag == 'tool_payload' else
                                  real['ok'] and checker(real['resp'], result['resp']))
            out[flag.replace('_payload', '_check')] = {'ok': bool(ok)}
            out['pass'] = out['pass'] and bool(ok)
            out['timed_out'] |= bool(result.get('deadline'))
    if a.usability:
        recipe = json.loads(Path(a.recipe).read_text()) if a.recipe else None
        out['usability'] = usability(send, a.model, recipe, json.loads(Path(a.bank).read_text()),
                                     a.p90_max, p90_max_reason=a.p90_max_reason)
        out['timed_out'] |= any(r['deadline'] for r in out['usability']['items'])
    out['usability_gate'] = usability_gate(out.get('usability'), a.offline)
    print(json.dumps(out))
    return 0 if out['pass'] and (not a.usability or out['usability_gate']['ok']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
