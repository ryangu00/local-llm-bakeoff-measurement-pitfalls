#!/usr/bin/env python3
"""Loopback-only synthetic HTTP/SSE failure fixtures; no model is loaded."""
import argparse
from contextlib import contextmanager
import http.server
import json
import threading
import time

# Delays and counts are synthetic values from the reference sketch.
class StubServer(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address):
        super().__init__(address, Handler)
        self.stop_event = threading.Event()
        self.hang_started = threading.Event()
        self.hang_finished = threading.Event()
        self.requests_seen = []


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send_body(self, body, status=200):
        encoded = json.dumps(body).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_POST(self):
        try:
            self.respond()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def respond(self):
        payload = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}')
        self.server.requests_seen.append(payload)
        if self.path == '/need-key' and self.headers.get('Authorization') != 'Bearer fixture':
            self.send_body({'error': 'API key required'}, 401)
            return
        if self.path == '/sse' or payload.get('stream'):
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            def event(data):
                self.wfile.write(b'data: ' + json.dumps(data).encode() + b'\n\n')
                self.wfile.flush()
            event({'choices': [{'delta': {'role': 'assistant'}}]})
            time.sleep(0.2)
            event({'model': 'keepalive', 'choices': []})
            time.sleep(0.2)
            event({'choices': [{'delta': {'content': 'hi'}}]})
            self.wfile.write(b'data: [DONE]\n\n')
            return
        if self.path == '/hang':
            self.send_response(200); self.end_headers()
            self.server.hang_started.set()
            self.server.stop_event.wait()
            self.server.hang_finished.set()
            return
        body = {'choices': [{'message': {'content': 'ok'}, 'finish_reason': 'stop'}],
                'usage': {'prompt_tokens': 7, 'completion_tokens': 3}}
        if self.path.startswith('/dribble'):
            self.send_response(200); self.end_headers()
            for _ in range(4):
                self.wfile.write(b' '); self.wfile.flush(); time.sleep(0.5)
            if self.path == '/dribble-error':
                body = {'error': 'aborted'}
            self.wfile.write(json.dumps(body).encode())
            return
        if self.path == '/truncated':
            body['choices'][0].update(message={'content': '```python\npass\n```'}, finish_reason='length')
        if payload.get('tools'):
            body['choices'][0]['message']['tool_calls'] = [
                {'type': 'function', 'function': {'name': 'inspect', 'arguments': '{}'}}]
        if any(isinstance(m.get('content'), list) for m in payload.get('messages', [])):
            body['usage']['prompt_tokens'] += 60
        if any(m.get('reasoning_content') for m in payload.get('messages', [])):
            body['usage']['prompt_tokens'] += 60
        self.send_body(body)


@contextmanager
def running():
    server = StubServer(('127.0.0.1', 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f'http://127.0.0.1:{server.server_address[1]}'
    finally:
        server.stop_event.set()
        server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port', type=int, default=8000)
    a = p.parse_args()
    server = StubServer(('127.0.0.1', a.port))
    print(f'Synthetic stub: http://127.0.0.1:{server.server_address[1]}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop_event.set(); server.server_close()
