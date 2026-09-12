"""Bounded cleanup against a real child process with unresponsive protocol I/O."""
import subprocess
import sys
import tempfile
import time
import signal
import unittest
from unittest.mock import patch

from arkui_agent.repository import ClangdSemanticProvider, ClangdProtocolError, RepositoryWorkspace


CHILD = '''
import sys,json,time
headers={}
while True:
    line=sys.stdin.buffer.readline()
    if line==b"\\r\\n": break
    key,_,value=line.partition(b":")
    headers[key.lower()]=value.strip()
request=json.loads(sys.stdin.buffer.read(int(headers[b"content-length"])))
payload=json.dumps({"jsonrpc":"2.0","id":request["id"],"result":{"capabilities":{}}}).encode()
sys.stdout.buffer.write(b"Content-Length: "+str(len(payload)).encode()+b"\\r\\n\\r\\n"+payload)
sys.stdout.buffer.flush()
time.sleep(60)
'''

PROTOCOL_CHILD = '''
import sys,json
def send(message):
    payload=json.dumps(message).encode()
    sys.stdout.buffer.write(b"Content-Length: "+str(len(payload)).encode()+b"\\r\\n\\r\\n"+payload)
    sys.stdout.buffer.flush()
while True:
    headers={}
    while True:
        line=sys.stdin.buffer.readline()
        if not line: sys.exit(0)
        if line==b"\\r\\n": break
        key,_,value=line.partition(b":")
        headers[key.lower()]=value.strip()
    request=json.loads(sys.stdin.buffer.read(int(headers[b"content-length"])))
    method=request.get("method")
    if method=="crash":
        sys.stderr.write("y"*20000)
        sys.stderr.write("synthetic fatal: allocation boundary\\n")
        sys.stderr.flush()
        sys.exit(71)
    if method=="textDocument/didOpen":
        for i in range(64):
            send({"method":"textDocument/publishDiagnostics", "params":{"data":"x"*8192}})
    if method=="exit": sys.exit(0)
    if "id" in request:
        send({"id":request["id"], "result":{"capabilities":{}} if method=="initialize" else []})
'''


class ClangdCleanupTests(unittest.TestCase):
    def test_console_interrupt_is_deferred_until_cleanup_finishes(self):
        from arkui_agent.repository.interrupts import defer_keyboard_interrupt
        events = []
        with self.assertRaises(KeyboardInterrupt):
            with defer_keyboard_interrupt():
                signal.getsignal(signal.SIGINT)(signal.SIGINT, None)
                events.append("cleanup finished")
        self.assertEqual(events, ["cleanup finished"])

    def test_keyboard_interrupt_keeps_original_reason_and_reaps_child(self):
        with tempfile.TemporaryDirectory() as root:
            provider = self.provider(root, timeout=30)
            started = time.monotonic()
            with self.assertRaises(KeyboardInterrupt):
                with provider:
                    raise KeyboardInterrupt
            self.assertTrue(provider.is_closed)
            self.assertIsNotNone(provider._process.poll())
            self.assertLess(time.monotonic() - started, 8)

    def provider(self, root, timeout=0.1, child=CHILD):
        real_popen = subprocess.Popen
        def launch(command, **kwargs):
            return real_popen([sys.executable, "-u", "-c", child], **kwargs)
        with patch("arkui_agent.repository.clangd.shutil.which", return_value=sys.executable), \
             patch("arkui_agent.repository.clangd.subprocess.Popen", side_effect=launch):
            return ClangdSemanticProvider(RepositoryWorkspace(root), request_timeout=timeout)

    def test_success_and_failure_teardown_are_bounded_and_reap_owned_child(self):
        with tempfile.TemporaryDirectory() as root:
            for failure in (False, True):
                provider = self.provider(root, timeout=30)
                started = time.monotonic()
                try:
                    if failure:
                        with self.assertRaisesRegex(ValueError, "original semantic failure"):
                            with provider:
                                raise ValueError("original semantic failure")
                    else:
                        with provider:
                            pass
                    self.assertIsNotNone(provider._process.poll())
                    self.assertTrue(provider.is_closed)
                    self.assertLess(time.monotonic() - started, 8)
                    self.assertTrue(provider.cleanup_diagnostics)
                    provider.close()
                finally:
                    if provider._process.poll() is None:
                        provider._process.kill()
                        provider._process.wait(timeout=2)

    def test_blocked_write_times_out_and_cleanup_does_not_hang(self):
        with tempfile.TemporaryDirectory() as root:
            provider = self.provider(root, timeout=1)
            try:
                with self.assertRaisesRegex(ClangdProtocolError, "timed out"):
                    with provider:
                        provider._notify("large-notification", {"text": "x" * (2 * 1024 * 1024)})
                self.assertIsNotNone(provider._process.poll())
            finally:
                provider.close()

    def test_cleanup_exception_never_replaces_original_failure(self):
        provider = object.__new__(ClangdSemanticProvider)
        provider.cleanup_diagnostics = ()
        original = ValueError("original semantic failure")
        with patch.object(provider, "close", side_effect=OSError("cleanup failed")):
            provider.__exit__(ValueError, original, None)
        self.assertIn("cleanup failed", original.__notes__[0])

    def test_process_failure_reports_request_file_exit_stderr_and_progress(self):
        with tempfile.TemporaryDirectory() as root:
            provider = self.provider(root, timeout=3, child=PROTOCOL_CHILD)
            with self.assertRaises(ClangdProtocolError) as raised:
                with provider:
                    provider._transport.request("crash", {"textDocument": {"uri": "file:///failed.cpp"}})
            detail = str(raised.exception)
            for expected in ("crash", "failed.cpp", "exit_code=71", "synthetic fatal", "last_success=",
                             "requests_completed=1", "didOpen_completed=0"):
                self.assertIn(expected, detail)
            self.assertEqual(provider._process.poll(), 71)
            self.assertLessEqual(len(provider._transport.stderr_tail), 8192)
            self.assertLess(len(detail), 10000)
            self.assertFalse(provider._transport._reader.is_alive())
            self.assertFalse(provider._transport._stderr_reader.is_alive())

    def test_notifications_are_drained_while_writing_and_write_failure_has_context(self):
        with tempfile.TemporaryDirectory() as root:
            provider = self.provider(root, timeout=3, child=PROTOCOL_CHILD)
            with provider:
                for i in range(8):
                    provider._notify("textDocument/didOpen", {"textDocument": {
                        "uri": f"file:///file-{i}.cpp", "text": "x" * 100000}})
                provider._transport.request("ready")
                self.assertEqual(provider._transport.open_count, 8)
                with patch.object(provider._transport, "_write", side_effect=BrokenPipeError("pipe closed")):
                    with self.assertRaises(ClangdProtocolError) as raised:
                        provider._notify("textDocument/didOpen", {"textDocument": {"uri": "file:///broken.cpp"}})
                for expected in ("didOpen", "broken.cpp", "pipe closed", "exit_code=", "last_success=", "stage="):
                    self.assertIn(expected, str(raised.exception))
