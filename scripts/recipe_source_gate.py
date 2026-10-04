#!/usr/bin/env python3
"""Recipe-source and arm-naming gate, with a positive field allow-list."""
import argparse
import hashlib
import json
from pathlib import Path
import re


def _model_section(text, model):
    lines, start, level = text.splitlines(), None, 0
    for i, line in enumerate(lines):
        heading = re.match(r'^(#{1,6})\s+(.+?)\s*#*$', line)
        if not heading:
            continue
        if start is None:
            if heading.group(2) == model:
                start, level = i, len(heading.group(1))
        elif len(heading.group(1)) <= level:
            return '\n'.join(lines[start:i])
    return None if start is None else '\n'.join(lines[start:])


def _verdict_fields(section, verdict):
    fields, active = set(), False
    for line in section.splitlines():
        if line.startswith('**'):
            active = line.strip() == '**' + verdict + '**'
        elif line.startswith('#'):
            active = False
        elif active and re.match(r'\d+\.\s', line):
            token = re.search(r'`([^`]+)`', line)
            if token:
                fields.add(token.group(1).split('=')[0].strip())
    return fields


def _refuted_fields(section):
    return _verdict_fields(section, 'Refuted')


def verify_ref(model, recipe, research_root):
    reference = re.fullmatch(r'\s*(\S+)\s+sha256:([0-9a-f]{12,64})\s*', str(recipe.get('verified_by') or ''))
    if not reference:
        return 'verified_by requires a report path and a hash prefix'
    root = Path(research_root).resolve()
    path = (root / reference.group(1)).resolve()
    if not path.is_relative_to(root) or not re.fullmatch(r'VERIFY[^/]*\.md', path.name):
        return 'verification report must be a VERIFY*.md file inside the research root'
    try:
        raw = path.read_bytes()
    except OSError:
        return 'verification report is unreadable'
    if not hashlib.sha256(raw).hexdigest().startswith(reference.group(2)):
        return 'verification report hash mismatch'
    section = _model_section(raw.decode('utf-8'), model)
    if section is None:
        return 'verification report has no exact model heading'
    official = _verdict_fields(section, 'Confirmed official')
    inferred = _verdict_fields(section, 'Confirmed but inferred')
    refuted = _refuted_fields(section)
    bad = []
    for field, kind in recipe.get('field_sources', {}).items():
        if kind != 'official':
            continue
        negative = any(field == f or field.endswith('.' + f) for f in inferred | refuted)
        if field not in official or negative:
            bad.append(field)
    if bad:
        return 'fields lack exclusive confirmed-official evidence: ' + ', '.join(sorted(bad))
    return None


def resolve_config(model, recipe, research_root, arm='vendor', reason='', overrides=None):
    overrides = overrides or {}
    if arm not in ('vendor', 'harness-uniform'):
        raise ValueError('unknown requested arm')
    if arm == 'harness-uniform':
        if not reason.strip():
            raise ValueError('harness-uniform requires --reason')
        return {'recipe_arm': arm, 'reason': reason.strip(), 'recipe': None,
                'overrides': overrides, 'informed': [], 'limitations': []}
    if recipe is None:
        raise ValueError('no recipe; use an explicit harness-uniform arm with --reason')
    if not isinstance(recipe.get('limitations'), list):
        raise ValueError('recipe requires a limitations list, even if empty')
    sampling = recipe.get('sampling') or {}
    if any(k not in sampling for k in ('temperature', 'top_p')):
        raise ValueError('recipe sampling requires temperature and top_p')
    for field in ('chat_kwargs', 'max_tokens', 'system', 'preserve_reasoning', 'sources', 'field_sources'):
        if field not in recipe:
            raise ValueError('recipe is missing ' + field)
    keys = [f'sampling.{k}' for k in sampling] + [f'chat_kwargs.{k}' for k in recipe['chat_kwargs']]
    keys += ['max_tokens', 'preserve_reasoning', 'system']
    problem = verify_ref(model, recipe, research_root)
    informed = keys if problem else [k for k in keys if recipe['field_sources'].get(k) != 'official']
    name = 'vendor-overridden' if overrides else 'vendor-informed' if informed else 'vendor'
    return {'recipe_arm': name, 'informed': informed, 'verify_problem': problem,
            'overrides': overrides, 'limitations': recipe['limitations'], 'recipe': recipe}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model', required=True); p.add_argument('--recipe')
    p.add_argument('--research-root', default='fixtures/research')
    p.add_argument('--recipe-arm', default='vendor', choices=['vendor', 'harness-uniform'])
    p.add_argument('--reason', default=''); p.add_argument('--overrides', default='{}')
    a = p.parse_args()
    try:
        recipe = json.loads(Path(a.recipe).read_text()) if a.recipe else None
        out = resolve_config(a.model, recipe, a.research_root, a.recipe_arm, a.reason, json.loads(a.overrides))
    except (ValueError, OSError) as error:
        p.exit(1, str(error) + '\n')
    print(json.dumps(out, indent=2))


if __name__ == '__main__':
    main()
