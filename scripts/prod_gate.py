#!/usr/bin/env python3
"""Route-table isolation. LAN, hostname and tunnel aliases remain unresolved."""
import argparse
import ipaddress
import json
import os
import socket
import sys
import urllib.request
from urllib.parse import urlparse


def canon_host(host):
    host = (host or '').rstrip('.').lower()
    if host == 'localhost' or host.endswith('.localhost'):
        return 'loopback'
    try:
        addresses = {ipaddress.ip_address(a[4][0].split('%')[0]) for a in
                     socket.getaddrinfo(host, None, flags=socket.AI_NUMERICHOST)}
    except (OSError, ValueError, UnicodeError):
        return host
    addresses = {getattr(ip, 'ipv4_mapped', None) or ip for ip in addresses}
    if any(ip.is_loopback or ip.is_unspecified for ip in addresses):
        return 'loopback'
    return str(min(addresses, key=str))


def hostport(url):
    parsed = urlparse(url if '://' in url else 'http://' + url)
    return canon_host(parsed.hostname), parsed.port or (443 if parsed.scheme == 'https' else 80)


def litellm_bases(url, timeout=5, api_key=''):
    base = url.rstrip('/').removesuffix('/v1')
    req = urllib.request.Request(base + '/model/info', headers={'Authorization': 'Bearer ' + api_key} if api_key else {})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        data = json.load(response)
    rows = data.get('data') if isinstance(data, dict) else None
    if not isinstance(rows, list) or not rows:
        raise ValueError('route table has no nonempty data list')
    bases = [(m.get('model_name'), (m.get('litellm_params') or {}).get('api_base') or
              (m.get('model_info') or {}).get('api_base')) for m in rows]
    if not any(base for _, base in bases):
        raise ValueError('no deployment API bases')
    return bases


def model_bases(bases, model):
    selected = [base for name, base in bases if name == model]
    if not model or not selected or any(not isinstance(base, str) or not base.strip() for base in selected):
        raise ValueError('cannot resolve all deployments of the requested alias')
    return selected


def block(why):
    print('[production isolation] ' + why, file=sys.stderr)
    raise SystemExit(3)


def check(base_url, litellm_url='http://127.0.0.1:4000', allow='', model='', api_key='', via_gateway=False):
    allow = allow.strip()
    hp = hostport(base_url)
    gateway = via_gateway or hp == hostport(litellm_url) or hp == ('loopback', 4000)
    rec = {'base_url': base_url, 'allow_shared_prod': bool(allow), 'reason': allow,
           'verified': True, 'litellm_hits': [], 'shared': False}
    try:
        bases = litellm_bases(litellm_url, api_key=api_key)
        endpoints = {hp}
        if gateway:
            rec['deployment_bases'] = model_bases(bases, model)
            endpoints = {hostport(base) for base in rec['deployment_bases']}
        rec['litellm_hits'] = [name for name, base in bases if base and hostport(base) in endpoints]
    except Exception as error:
        rec['verified'] = False
        rec['note'] = 'production isolation unverified: ' + type(error).__name__
        print('WARNING: ' + rec['note'], file=sys.stderr)
        if gateway:
            block('gateway deployments unresolved')
    rec['shared'] = bool(rec['litellm_hits'])
    if rec['shared'] and not allow:
        block('benchmark endpoint is in the production route table; a recorded reason is required to override')
    return rec


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base-url', required=True)
    p.add_argument('--litellm-url', default='http://127.0.0.1:4000')
    p.add_argument('--model', default=''); p.add_argument('--via-gateway', action='store_true')
    p.add_argument('--allow-shared-prod', default=''); p.add_argument('--api-key-env', default='')
    a = p.parse_args()
    print(json.dumps(check(a.base_url, a.litellm_url, a.allow_shared_prod, a.model,
                           os.environ.get(a.api_key_env, '') if a.api_key_env else '', a.via_gateway)))
