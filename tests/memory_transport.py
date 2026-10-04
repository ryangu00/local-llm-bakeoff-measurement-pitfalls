"""In-memory transport for the real stub handler; no sockets or external I/O.

This checks handler/client semantics, not operating-system HTTP framing.
Use RUN_LOOPBACK_TESTS=1 to select actual loopback sockets where permitted.
"""
from contextlib import contextmanager
import io
import json
import queue
import threading
from types import SimpleNamespace
import urllib.error
from unittest.mock import patch
import stub_server


class Response:
    def __init__(self, timeout):
        self.timeout = timeout
        self.parts = queue.Queue()
        self.status_ready = threading.Event()
        self.status = None
        self.buffer = b''

    def write(self, data):
        self.parts.put(data)
        return len(data)

    def flush(self):
        pass

    def close(self):
        pass

    def finish(self):
        self.parts.put(None)

    def read(self, size=-1):
        data = self.buffer; self.buffer = b''
        while True:
            try:
                chunk = self.parts.get(timeout=self.timeout)
            except queue.Empty:
                raise TimeoutError('synthetic socket read timeout') from None
            if chunk is None:
                return data
            data += chunk
            if size >= 0 and len(data) >= size:
                self.buffer = data[size:]
                return data[:size]

    def __iter__(self):
        pending = b''
        while True:
            try:
                part = self.parts.get(timeout=self.timeout)
            except queue.Empty:
                raise TimeoutError('synthetic socket read timeout') from None
            if part is None:
                if pending:
                    yield pending
                return
            pending += part
            while b'\n' in pending:
                line, pending = pending.split(b'\n', 1)
                yield line + b'\n'

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@contextmanager
def running():
    state = SimpleNamespace(stop_event=threading.Event(), hang_started=threading.Event(),
                            hang_finished=threading.Event(), requests_seen=[])
    threads = []
    def open_request(request, timeout=900):
        from urllib.parse import urlparse
        response = Response(timeout)
        handler = object.__new__(stub_server.Handler)
        handler.path = urlparse(request.full_url).path
        data = request.data or b'{}'
        handler.rfile = io.BytesIO(data)
        handler.wfile = response
        handler.server = state
        handler.headers = {'Content-Length': str(len(data)), 'Authorization': request.get_header('Authorization')}
        handler.send_response = lambda status: setattr(response, 'status', status)
        handler.send_header = lambda *args: None
        handler.end_headers = response.status_ready.set
        def work():
            try:
                handler.respond()
            finally:
                response.status_ready.set()
                response.finish()
        thread = threading.Thread(target=work, daemon=True)
        threads.append(thread); thread.start()
        if not response.status_ready.wait(timeout):
            raise TimeoutError('synthetic header timeout')
        if response.status >= 400:
            raise urllib.error.HTTPError(request.full_url, response.status, 'synthetic HTTP error', {}, response)
        return response
    with patch('urllib.request.urlopen', side_effect=open_request):
        try:
            yield state, 'http://127.0.0.1:8000'
        finally:
            state.stop_event.set()
            for thread in threads:
                thread.join(5)
