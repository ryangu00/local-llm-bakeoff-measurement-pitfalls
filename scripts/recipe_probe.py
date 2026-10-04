#!/usr/bin/env python3
"""Recipe acceptance, reasoning-token proxy and offline rendering comparison."""
import argparse
import json
import os
from pathlib import Path
import re
from preflight import post

U, T1, T2, R1, R2 = 'PROBE-USER-Q', 'PROBE-TOOL-RESULT-1', 'PROBE-TOOL-RESULT-2', 'PROBE-REASONING-1', 'PROBE-REASONING-2'
OPEN = re.compile(r'<think>|<mm:think>|<\|content_thinking\|>')
EMPTY = re.compile(r'<(think|mm:think)>\s*</\1>|<\|content_thinking\|>\s*<\|end_message\|>')
TOOLS = [{'type': 'function', 'function': {'name': 'inspect', 'description': 'Inspect a synthetic fixture',
          'parameters': {'type': 'object', 'properties': {'path': {'type': 'string'}}, 'required': ['path']}}}]


def history():
    call = lambda i: [{'id': f'call{i}', 'type': 'function', 'function':
                      {'name': 'inspect', 'arguments': {'path': f'fixture{i}'}}}]
    return [{'role': 'user', 'content': U},
            {'role': 'assistant', 'content': '', 'reasoning_content': R1, 'tool_calls': call(1)},
            {'role': 'tool', 'tool_call_id': 'call1', 'content': T1},
            {'role': 'assistant', 'content': '', 'reasoning_content': R2, 'tool_calls': call(2)},
            {'role': 'tool', 'tool_call_id': 'call2', 'content': T2}]


def _seg(text, a, b):
    start, end = text.find(a), text.find(b)
    return text[start + len(a):end] if 0 <= start < end else None


def check_render(text, reference=None):
    bad = []
    for i, (start, end, marker) in enumerate(((U, T1, R1), (T1, T2, R2)), 1):
        segment = _seg(text, start, end)
        if segment is None:
            bad.append(f'turn {i}: missing boundary markers')
            continue
        if len(OPEN.findall(segment)) != 1 or EMPTY.search(segment) or marker not in segment:
            bad.append(f'turn {i}: require one nonempty thinking block and the reasoning marker')
        if reference is not None:
            expected = _seg(reference, start, end)
            if expected is None or segment != expected:
                bad.append(f'turn {i}: not byte-identical to official rendering')
    return {'status': 'FAIL', 'why': bad} if bad else {'status': 'PASS'}


def render_check(model_dir, chat_kwargs, serving_render=None):
    if not model_dir or not Path(model_dir).is_dir():
        return {'status': 'SKIPPED', 'why': 'local model tokenizer directory unavailable'}
    try:
        from transformers import AutoTokenizer
        tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True, trust_remote_code=False)
    except Exception as error:
        return {'status': 'SKIPPED', 'why': 'local tokenizer unavailable: ' + type(error).__name__}
    try:
        reference = tokenizer.apply_chat_template(history(), tools=TOOLS, tokenize=False,
                                                  add_generation_prompt=True, **chat_kwargs)
    except Exception as error:
        return {'status': 'FAIL', 'why': 'template rendering failed: ' + type(error).__name__}
    if serving_render is None:
        return {'status': 'SKIPPED', 'why': 'serving-layer rendering unavailable; normalization equivalence unknown'}
    return check_render(serving_render, reference)


def probe(send, model, recipe, rendering):
    def request(messages, cap, tools=None):
        payload = {'model': model, 'messages': messages, 'max_tokens': cap,
                   'chat_template_kwargs': recipe['chat_kwargs'], **recipe['sampling']}
        if tools:
            payload['tools'] = tools
        return send(payload)
    accepted = request([{'role': 'user', 'content': 'Reply with one word: ok'}], recipe['max_tokens'])
    without, with_reasoning = history(), history()
    for message in without:
        message.pop('reasoning_content', None)
    for message in with_reasoning:
        if message['role'] == 'assistant':
            message['reasoning_content'] = 'marker ' * 60
    first = request(without, 1, TOOLS); second = request(with_reasoning, 1, TOOLS)
    try:
        before = first['resp']['usage']['prompt_tokens']
        after = second['resp']['usage']['prompt_tokens']
        echo = first['ok'] and second['ok'] and after - before >= 60
    except (KeyError, TypeError):
        before, after, echo = None, None, False
    out = {'accept': {'ok': accepted['ok']}, 'render_check': rendering,
           'reasoning_passthrough': {'ok': echo, 'prompt_tokens_without': before, 'prompt_tokens_with': after}}
    out['pass'] = (accepted['ok'] and (not recipe.get('preserve_reasoning') or echo)
                   and rendering['status'] == 'PASS')
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--rendered'); p.add_argument('--official'); p.add_argument('--model-dir')
    p.add_argument('--recipe'); p.add_argument('--model', default='synthetic-model')
    p.add_argument('--base-url'); p.add_argument('--api-key-env', default='')
    a = p.parse_args()
    recipe = json.loads(Path(a.recipe).read_text()) if a.recipe else None
    rendered = Path(a.rendered).read_text() if a.rendered else None
    if a.official:
        if rendered is None:
            p.error('--official requires --rendered')
        rendering = check_render(rendered, Path(a.official).read_text())
    else:
        rendering = render_check(a.model_dir, recipe.get('chat_kwargs', {}) if recipe else {}, rendered)
    out = {'render_check': rendering, 'pass': rendering['status'] == 'PASS'}
    if a.base_url:
        if not recipe:
            p.error('--base-url requires --recipe')
        key = os.environ.get(a.api_key_env, '') if a.api_key_env else ''
        out = probe(lambda payload: post(a.base_url.rstrip('/') + '/chat/completions', payload, 600, key),
                    a.model, recipe, rendering)
    print(json.dumps(out)); return 0 if out['pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
