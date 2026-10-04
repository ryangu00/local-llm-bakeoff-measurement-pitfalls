"""Synthetic tests only; temporary files stay inside the repository."""
import copy
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import math
import os
import runpy
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import check_run
import check_same_arm
import greedy_compare
import prefill_ttft
import preflight
import prod_gate
import recipe_probe
import recipe_source_gate as recipes
import speed_bench
import stub_server
import trunc_credit_scan
import memory_transport


def cli(script, *args):
    return subprocess.run([sys.executable, '-B', str(ROOT / 'scripts' / script), *map(str, args)],
                          cwd=ROOT, capture_output=True, text=True, timeout=30)


def load(path):
    return json.loads((ROOT / path).read_text())


class SameArmTests(unittest.TestCase):
    def setUp(self):
        self.a = load('fixtures/arm-a.json')
        self.b = load('fixtures/arm-b.json')

    def test_equal(self):
        self.assertTrue(check_same_arm.check(self.a, self.a)['ok'])

    def test_every_listed_difference_blocks(self):
        for field in check_same_arm.FIELDS:
            with self.subTest(field=field):
                b = {**self.a, field: 'different synthetic value'}
                self.assertFalse(check_same_arm.check(self.a, b)['ok'])

    def test_missing_cannot_be_intentional(self):
        b = {**self.a}; b.pop('served_identity')
        self.assertFalse(check_same_arm.check(self.a, b, ['served_identity'])['ok'])
        self.assertFalse(check_same_arm.check({}, {})['ok'])

    def test_intentional_note_and_cli(self):
        out = check_same_arm.check(self.a, self.b, ['grader_version'])
        self.assertTrue(out['ok']); self.assertEqual(out['notes'], ['intentional difference: grader_version'])
        a, b = ROOT / 'fixtures/arm-a.json', ROOT / 'fixtures/arm-b.json'
        self.assertEqual(cli('check_same_arm.py', a, b).returncode, 1)
        p = cli('check_same_arm.py', a, b, '--intentional', 'grader_version')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('intentional difference', p.stdout)

    def test_unknown_intentional_field(self):
        with self.assertRaises(ValueError):
            check_same_arm.check(self.a, self.b, ['misspelled'])


class ScoringTests(unittest.TestCase):
    def test_scan_flags_credit(self):
        rows = list(trunc_credit_scan.scan(ROOT / 'fixtures/runs'))
        row = next(r for r in rows if r['file'].startswith('fixture-code'))
        self.assertEqual((row['items'], row['truncated'], row['credited']), (2, 1, 1))
        self.assertEqual(row['without_credit'], 50.0)  # Synthetic fixture arithmetic.
        self.assertEqual(row['separated_reasoning_percent'], 50.0)

    def test_run_summary_errors(self):
        out = check_run.summarize(ROOT / 'fixtures/runs/synthetic')
        self.assertEqual(out['categories_with_errors'], ['fixture-errors-run1.jsonl'])
        self.assertEqual(cli('check_run.py', 'fixtures/runs/synthetic').returncode, 0)
        self.assertEqual(cli('trunc_credit_scan.py', 'fixtures/runs').returncode, 0)

    def test_empty_and_equal_greedy(self):
        empty = load('fixtures/greedy-empty.json')['greedy']
        equal = load('fixtures/greedy-equal-a.json')['greedy']
        self.assertEqual(greedy_compare.compare(empty, empty)['verdict'], 'invalid')
        self.assertEqual(greedy_compare.compare(equal, equal)['verdict'], 'identical')
        self.assertEqual(greedy_compare.compare([], [])['verdict'], 'invalid')
        self.assertEqual(greedy_compare.compare(equal, equal + equal)['verdict'], 'invalid')
        self.assertEqual(cli('greedy_compare.py', 'fixtures/greedy-empty.json', 'fixtures/greedy-empty.json').returncode, 2)
        self.assertEqual(cli('greedy_compare.py', 'fixtures/greedy-equal-a.json', 'fixtures/greedy-equal-b.json').returncode, 0)

    def test_first_divergence(self):
        a = [{'reasoning': 'same', 'text': 'alpha'}]
        b = [{'reasoning': 'same', 'text': 'alphb'}]
        out = greedy_compare.compare(a, b)
        self.assertEqual(out['verdict'], 'different')
        self.assertEqual(out['rows'][0]['first_divergence'], len('same\n<<CONTENT>>\nalph'))


class UsabilityTests(unittest.TestCase):
    def fake(self, seconds, failures=None):
        pending = iter(enumerate(seconds)); sent = []
        def send(payload, timeout):
            index, elapsed = next(pending); sent.append(payload)
            if failures and index in failures:
                return {'ok': False, 'secs': elapsed, **failures[index]}
            return {'ok': True, 'secs': elapsed, 'resp': {'usage': {'completion_tokens': 3}}}
        return send, sent

    def measure(self, seconds, threshold=30, reason='', failures=None, recipe=None):
        send, sent = self.fake(seconds, failures)
        return preflight.usability(send, 'synthetic-model', recipe, load('fixtures/bank.json'),
                                   threshold, p90_max_reason=reason), sent

    def test_synthetic_fast_and_slow(self):
        fast, _ = self.measure([2.8, 3.1, 3.2, 3.5, 4.0])
        slow, _ = self.measure([8, 15, 40, 95, 95])
        self.assertEqual((fast['status'], fast['p90_secs']), ('INTERACTIVE', 3.8))
        self.assertEqual((slow['status'], slow['p90_secs']), ('NOT_INTERACTIVE', 95))
        self.assertTrue(preflight.usability_gate(fast)['ok'])
        self.assertFalse(preflight.usability_gate(slow)['ok'])

    def test_recipe_fields_and_sequential_questions(self):
        recipe = load('configs/Qwen3.8-Flash-Next-1M.json')
        _, sent = self.measure([2.8, 3.1, 3.2, 3.5, 4.0], recipe=recipe)
        self.assertEqual(len(sent), 5)
        for payload in sent:
            self.assertEqual(payload['max_tokens'], 32768)
            self.assertEqual(payload['chat_template_kwargs'], recipe['chat_kwargs'])
            self.assertEqual(payload['top_k'], 20)

    def test_unmeasured_errors_offline_and_whitespace(self):
        self.assertFalse(preflight.usability_gate(None)['ok'])
        measurement, _ = self.measure([8, 15, 40, 95, 95], failures={0: {'http': 401}})
        self.assertEqual(measurement['status'], 'ERROR')
        self.assertFalse(preflight.usability_gate(measurement, '   ')['ok'])
        self.assertEqual(preflight.usability_gate(measurement, 'offline batch')['offline'], 'offline batch')

    def test_deadline_is_lower_bound_not_error(self):
        measurement, _ = self.measure([2.8, 3.1, 3.2, 3.5, 4.0], failures={4: {'deadline': True}})
        self.assertEqual(measurement['errors'], 0)
        self.assertEqual(measurement['items'][4]['secs'], 120)
        self.assertEqual(measurement['status'], 'NOT_INTERACTIVE')

    def test_loosened_threshold_reason(self):
        measurement, _ = self.measure([8, 15, 40, 95, 95], 120)
        self.assertFalse(preflight.usability_gate(measurement)['ok'])
        measurement['p90_max_reason'] = '  '
        self.assertFalse(preflight.usability_gate(measurement)['ok'])
        measurement['p90_max_reason'] = 'declared offline latency allowance'
        self.assertTrue(preflight.usability_gate(measurement)['ok'])

    def test_invalid_thresholds_refused_before_post(self):
        for value in (float('nan'), float('inf'), -1, 0):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.measure([8, 15, 40, 95, 95], value)
            with self.assertRaises(ValueError):
                preflight.usability_gate({'status': 'INTERACTIVE', 'p90_max': value}, 'offline')
        self.assertNotEqual(cli('preflight.py', '--p90-max', 'nan').returncode, 0)

    def test_tool_and_image_negative_cases(self):
        response = {'choices': [{'message': {'content': 'tool markup'}}], 'usage': {'prompt_tokens': 7}}
        self.assertFalse(preflight.tool_check(response))
        self.assertFalse(preflight.image_check(response, response))
        self.assertFalse(preflight.image_check({}, response))
        response['choices'][0]['message']['tool_calls'] = [{}]
        self.assertFalse(preflight.tool_check(response))


class ProductionTests(unittest.TestCase):
    def check(self, base='http://127.0.0.1:8000/v1', allow='', model='', source='fixtures/route-table'):
        with redirect_stderr(io.StringIO()):
            return prod_gate.check(base, (ROOT / source).as_uri(), allow, model)

    def test_host_spellings(self):
        forms = ['localhost.', '127.0.0.1.', '127.1', '2130706433', '::ffff:127.0.0.1', '::1', 'probe.localhost']
        for host in forms:
            self.assertEqual(prod_gate.canon_host(host), 'loopback')
        self.assertEqual(prod_gate.canon_host(str(__import__('ipaddress').IPv4Address(0))), 'loopback')

    def test_hit_block_and_recorded_override(self):
        for reason in ('', '   '):
            with self.assertRaises(SystemExit) as raised:
                self.check(allow=reason)
            self.assertEqual(raised.exception.code, 3)
        out = self.check(allow='dedicated evaluation window')
        self.assertTrue(out['shared']); self.assertTrue(out['verified'])
        self.assertEqual(out['reason'], 'dedicated evaluation window')

    def test_all_loopback_spellings_block(self):
        for host in ['localhost.', '127.0.0.1.', '127.1', '2130706433', '[::ffff:127.0.0.1]', '[::1]']:
            with self.subTest(host=host), self.assertRaises(SystemExit):
                self.check(base=f'http://{host}:8000/v1')

    def test_empty_table_and_different_port(self):
        self.assertFalse(self.check(source='fixtures/empty-route-table')['verified'])
        out = self.check(base='http://127.0.0.1:8901/v1')
        self.assertTrue(out['verified']); self.assertFalse(out['shared'])

    def test_gateway_alias_and_unknown_alias(self):
        for model in ('synthetic-route', 'missing'):
            with self.assertRaises(SystemExit) as raised:
                self.check(base='http://127.0.0.1:4000/v1', model=model)
            self.assertEqual(raised.exception.code, 3)

    def test_malformed_tables_are_unverified(self):
        for body in ({'error': 'fixture'}, {}, [], {'data': [{'model_name': 'fixture'}]}):
            with patch.object(prod_gate.urllib.request, 'urlopen', return_value=io.BytesIO(json.dumps(body).encode())):
                self.assertFalse(self.check()['verified'])

    def test_cli_exit_three(self):
        p = cli('prod_gate.py', '--base-url', 'http://127.0.0.1:8000/v1',
                '--litellm-url', (ROOT / 'fixtures/route-table').as_uri())
        self.assertEqual(p.returncode, 3, p.stderr)


class RecipeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.recipe = load('configs/Qwen3.8-Flash-Next-1M.json')
        self.model = self.recipe['model']
        self.recipe['field_sources'] = {k: 'official' for k in self.recipe['field_sources']}
        self.report = self.root / 'VERIFY-fixture.md'
        self.write_report()

    def write_report(self, official=None, inferred=(), refuted=(), heading=None):
        official = list(self.recipe['field_sources']) if official is None else official
        text = '# Verification fixture\n## ' + (heading or self.model) + '\n'
        for title, fields in [('Confirmed official', official), ('Confirmed but inferred', inferred), ('Refuted', refuted)]:
            text += '\n**' + title + '**\n'
            text += ''.join(f'{i}. `{field}`\n' for i, field in enumerate(fields, 1))
        self.report.write_text(text)
        self.recipe['verified_by'] = self.report.name + ' sha256:' + hashlib.sha256(self.report.read_bytes()).hexdigest()[:12]

    def resolve(self):
        return recipes.resolve_config(self.model, self.recipe, self.root)

    def test_official_and_placeholder(self):
        self.assertEqual(self.resolve()['recipe_arm'], 'vendor')
        example = load('configs/Qwen3.8-Flash-Next-1M.json')
        self.assertEqual(recipes.resolve_config(self.model, example, self.root)['recipe_arm'], 'vendor-informed')

    def test_inferred_relabel_cannot_pass(self):
        field = 'sampling.top_p'
        self.write_report(official=[k for k in self.recipe['field_sources'] if k != field], inferred=[field])
        self.assertEqual(self.resolve()['recipe_arm'], 'vendor-informed')
        self.assertIn(field, self.resolve()['verify_problem'])

    def test_conflicting_and_refuted_evidence(self):
        self.write_report(refuted=['top_p'])
        self.assertEqual(self.resolve()['recipe_arm'], 'vendor-informed')
        self.write_report(inferred=['sampling.top_p'])
        self.assertEqual(self.resolve()['recipe_arm'], 'vendor-informed')

    def test_hash_model_and_name_checks(self):
        for change in ('hash', 'heading', 'name'):
            self.write_report()
            if change == 'hash':
                self.report.write_text(self.report.read_text() + 'changed\n')
            elif change == 'heading':
                self.write_report(heading=self.model + '-other')
            else:
                target = self.root / 'notes.md'; target.write_bytes(self.report.read_bytes())
                self.recipe['verified_by'] = self.recipe['verified_by'].replace(self.report.name, target.name)
            self.assertEqual(self.resolve()['recipe_arm'], 'vendor-informed')

    def test_path_escape_and_symlink(self):
        research = self.root / 'research'; research.mkdir()
        for path in ('../VERIFY-fixture.md', 'VERIFY-link.md'):
            if 'link' in path:
                (research / path).symlink_to(self.report)
            self.recipe['verified_by'] = path + ' sha256:' + hashlib.sha256(self.report.read_bytes()).hexdigest()[:12]
            self.assertIsNotNone(recipes.verify_ref(self.model, self.recipe, research))

    def test_section_isolation(self):
        self.report.write_text('# Other model\n**Confirmed official**\n1. `sampling.top_p`\n'
                               + '## ' + self.model + '\n**Confirmed but inferred**\n1. `sampling.top_p`\n')
        self.recipe['verified_by'] = self.report.name + ' sha256:' + hashlib.sha256(self.report.read_bytes()).hexdigest()[:12]
        self.assertEqual(self.resolve()['recipe_arm'], 'vendor-informed')

    def test_missing_recipe_reason_sampling_and_limits(self):
        with self.assertRaises(ValueError):
            recipes.resolve_config(self.model, None, self.root)
        with self.assertRaises(ValueError):
            recipes.resolve_config(self.model, None, self.root, 'harness-uniform', ' ')
        for key in ('limitations', 'sampling'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                recipes.resolve_config(self.model, {k:v for k,v in self.recipe.items() if k != key}, self.root)
        self.assertEqual(recipes.resolve_config(self.model, None, self.root, 'harness-uniform', 'control')['recipe_arm'], 'harness-uniform')
        self.assertNotEqual(cli('recipe_source_gate.py', '--model', self.model).returncode, 0)

    def test_overrides_keep_source_information(self):
        self.recipe['verified_by'] = ''
        out = recipes.resolve_config(self.model, self.recipe, self.root, overrides={'max_tokens': 8000})
        self.assertEqual(out['recipe_arm'], 'vendor-overridden')
        self.assertTrue(out['informed']); self.assertTrue(out['verify_problem'])


class RenderTests(unittest.TestCase):
    def rendering(self, block):
        r = recipe_probe
        return f'{r.U}{block(r.R1)}{r.T1}{block(r.R2)}{r.T2}'

    def test_supported_markers(self):
        for start, end in [('<think>', '</think>'), ('<mm:think>', '</mm:think>'),
                           ('<|content_thinking|>', '<|end_message|>')]:
            good = self.rendering(lambda r: start+r+end)
            self.assertEqual(recipe_probe.check_render(good, good)['status'], 'PASS')

    def test_double_empty_dropped_wrong_marker(self):
        for block in (lambda r: '<think></think><think>'+r+'</think>',
                      lambda r: '<think>other</think><think>'+r+'</think>',
                      lambda r: '', lambda r: '<think>wrong</think>',
                      lambda r: '<|content_thinking|><|end_message|>'+r):
            self.assertEqual(recipe_probe.check_render(self.rendering(block))['status'], 'FAIL')

    def test_byte_equality(self):
        good = self.rendering(lambda r: '<think>'+r+'</think>')
        changed = self.rendering(lambda r: '<think>\n'+r+'\n</think>')
        self.assertEqual(recipe_probe.check_render(changed)['status'], 'PASS')
        self.assertEqual(recipe_probe.check_render(changed, good)['status'], 'FAIL')

    def test_cli_and_missing_tokenizer(self):
        self.assertEqual(cli('recipe_probe.py', '--rendered', 'fixtures/render-good.txt',
                             '--official', 'fixtures/render-good.txt').returncode, 0)
        self.assertEqual(cli('recipe_probe.py', '--rendered', 'fixtures/render-double.txt',
                             '--official', 'fixtures/render-good.txt').returncode, 1)
        self.assertEqual(recipe_probe.render_check(None, {})['status'], 'SKIPPED')

    def test_two_assistant_tool_turns_after_user(self):
        history = recipe_probe.history()
        self.assertEqual([m['role'] for m in history], ['user','assistant','tool','assistant','tool'])
        self.assertTrue(all(m.get('reasoning_content') and m.get('tool_calls') for m in history if m['role']=='assistant'))


class TransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = stub_server.running() if os.environ.get('RUN_LOOPBACK_TESTS') == '1' else memory_transport.running()
        cls.server, cls.url = cls.context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.context.__exit__(None, None, None)

    def run_cli(self, script, *args):
        if os.environ.get('RUN_LOOPBACK_TESTS') == '1':
            return cli(script, *args)
        out, err = io.StringIO(), io.StringIO()
        status = 0
        with patch.object(sys, 'argv', [script, *map(str, args)]), redirect_stdout(out), redirect_stderr(err):
            try:
                runpy.run_path(str(ROOT / 'scripts' / script), run_name='__main__')
            except SystemExit as exit_status:
                status = exit_status.code
        return subprocess.CompletedProcess([script], status, out.getvalue(), err.getvalue())

    def test_authentication_body(self):
        bad = preflight.post(self.url + '/need-key', {})
        self.assertFalse(bad['ok']); self.assertEqual(bad['http'], 401)
        self.assertIn('API key required', bad['body'])
        self.assertTrue(preflight.post(self.url + '/need-key', {}, key='fixture')['ok'])

    def test_socket_timeout_reset_by_whitespace(self):
        request = urllib.request.Request(self.url+'/dribble-error', b'{}')
        start = time.monotonic()
        with urllib.request.urlopen(request, timeout=1) as response:
            self.assertEqual(response.status, 200); body = json.load(response)
        self.assertGreater(time.monotonic()-start, 1)
        self.assertNotIn('choices', body)
        checked = preflight.post(self.url+'/dribble-error', {}, timeout=5)
        self.assertFalse(checked['ok']); self.assertIn('no choices', checked['err'])

    def test_wall_deadline_does_not_stop_server(self):
        result = preflight.post(self.url+'/hang', {}, timeout=0.2)
        self.assertTrue(result.get('deadline'), result)
        self.assertTrue(self.server.hang_started.is_set())
        self.assertFalse(self.server.hang_finished.is_set())

    def test_sse_skips_heartbeat_and_role(self):
        elapsed = prefill_ttft.measure(self.url+'/sse', 'synthetic-model', 'fixture')
        self.assertGreaterEqual(elapsed, 0.35)
        self.assertLess(elapsed, 5)

    def test_reasoning_token_also_counts(self):
        chunks = [b'data: {"model":"keepalive","choices":[]}\n',
                  b'data: {"choices":[{"delta":{"reasoning_content":"r"}}]}\n']
        elapsed, _ = prefill_ttft.first_real_chunk(chunks, 0, lambda: 0.4)
        self.assertEqual(elapsed, 0.4)
        with self.assertRaises(ValueError):
            prefill_ttft.first_real_chunk([b'data: [DONE]\n'], 0)

    def test_seed_repeat_is_visible(self):
        self.assertEqual(prefill_ttft.prompt(1000, 1), prefill_ttft.prompt(1000, 1))
        self.assertNotEqual(prefill_ttft.prompt(1000, 1), prefill_ttft.prompt(1000, 2))

    def test_speed_counts_nonce_and_greedy_input(self):
        first = speed_bench.call(self.url+'/v1', 'synthetic-model', '', 'fixture', 1)
        speed_bench.call(self.url+'/v1', 'synthetic-model', '', 'fixture', 1)
        x, y = self.server.requests_seen[-2:]
        self.assertNotEqual(x['messages'], y['messages'])
        self.assertTrue(x['messages'][0]['content'].startswith('[run '))
        self.assertEqual((first['prompt'], first['completion']), (7, 3))
        self.assertNotEqual(1000/first['secs'], first['prompt']/first['secs'])
        speed_bench.call(self.url+'/v1', 'synthetic-model', '', 'fixture', 1, fresh=False)
        self.assertEqual(self.server.requests_seen[-1]['messages'][0]['content'], 'fixture')
        self.assertEqual(speed_bench.med_drop_first([95, 2.8, 3.1, 3.2]), 3.1)

    def test_speed_cli_rates_equal_usage_over_elapsed(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            out = self.run_cli('speed_bench.py', '--base-url', self.url+'/v1', '--model', 'synthetic-model',
                      '--label', 'synthetic', '--runs', '2', '--conc', '2', '--prefill', '1000',
                      '--out', directory, '--greedy', '1')
            self.assertEqual(out.returncode, 0, out.stderr)
            result = json.loads((Path(directory)/'synthetic.json').read_text())
            for row in result['decode']['runs']:
                self.assertEqual(row['tps'], 3/row['secs'])
            for row in result['prefill']['1000']['runs']:
                self.assertEqual(row['prefill_tps'], 7/row['secs'])
            for row in result['concurrency']['2']['runs']:
                self.assertEqual(row['agg_tps'], row['tokens']/row['wall'])
            for line in out.stdout.splitlines():
                if line.startswith(('decode:', 'prefill:')):
                    left, value = line.split(' = ')
                    count, seconds = left.split(': ')[1].split(' / ')
                    expected_count = 3 if line.startswith('decode:') else 7
                    self.assertEqual(int(count), expected_count)
                    self.assertAlmostEqual(float(value.split()[0]), expected_count/float(seconds),
                                           delta=max(1, float(value.split()[0])*0.01))

    def test_preflight_cli_tool_image_usability(self):
        out = self.run_cli('preflight.py', '--base-url', self.url+'/v1', '--usability',
                  '--tool-payload', 'fixtures/tool-payload.json', '--image-payload', 'fixtures/image-payload.json')
        self.assertEqual(out.returncode, 0, out.stderr)
        result = json.loads(out.stdout)
        self.assertTrue(result['tool_check']['ok']); self.assertTrue(result['image_check']['ok'])
        self.assertTrue(result['usability_gate']['ok'])

    def test_truncated_response_and_recipe_probe(self):
        result = preflight.post(self.url+'/truncated', {})
        self.assertEqual(result['resp']['choices'][0]['finish_reason'], 'length')
        recipe = load('configs/Qwen3.8-Flash-Next-1M.json')
        send = lambda p: preflight.post(self.url+'/v1/chat/completions', p)
        out = recipe_probe.probe(send, 'synthetic-model', recipe, {'status':'PASS'})
        self.assertTrue(out['pass'])
        out = recipe_probe.probe(send, 'synthetic-model', recipe, {'status':'SKIPPED'})
        self.assertFalse(out['pass'])


if __name__ == '__main__':
    unittest.main()
