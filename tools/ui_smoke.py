#!/usr/bin/env python3
"""
End-to-end UI smoke test for the workbench (headless Chrome over the DevTools protocol).

Needs: the Django backend and the Vite dev server (or a built frontend) running, Ollama
with the models installed, and google-chrome. No Python packages beyond the standard library.

    python tools/ui_smoke.py                      # app on :5173, API on :8000
    python tools/ui_smoke.py --app http://host:5173 --api http://host:8000 --shots /tmp/shots

What it checks (each step prints PASS/FAIL; exit code 1 if any step failed):
  1. the chat page loads without JavaScript exceptions
  2. switching the interface to Hindi translates it and sets <html lang="hi">
  3. a question asked in Hindi mode gets an answer written in Devanagari
  4. "Answer ready" is announced to screen readers
  5. editing the sent question replaces the turn (still one question + one answer)
  6. regenerating an earlier answer (not the last one) works
  7. rating an answer (thumbs up) is stored on the server
  8. the Document Assistant and System Status pages render in Hindi
  9. System Status shows the 14-day trend, the per-model table and database / disk checks
 10. the OCR deep check passes (runs local OCR on a generated image)
 11. switching back to English restores the English interface

Only conversations created by this run are deleted afterwards; existing data is untouched.
"""

import argparse
import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request

DEVANAGARI = r"/[ऀ-ॿ]/"


class Browser:
    """Minimal DevTools-protocol client (one page, raw WebSocket, no dependencies)."""

    def __init__(self, port=9344, width=1280, height=900):
        self.profile = tempfile.mkdtemp(prefix="ui-smoke-")
        self.proc = subprocess.Popen(
            ["google-chrome", "--headless=new", f"--remote-debugging-port={port}", "--no-first-run",
             "--disable-gpu", f"--user-data-dir={self.profile}", f"--window-size={width},{height}", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        tabs = None
        for _ in range(100):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
                break
            except OSError:
                time.sleep(0.2)
        if tabs is None:
            raise SystemExit("Could not start google-chrome in headless mode.")
        ws_url = [t for t in tabs if t["type"] == "page"][0]["webSocketDebuggerUrl"]
        self.sock = socket.create_connection(("127.0.0.1", port))
        self.sock.settimeout(300)
        key = base64.b64encode(os.urandom(16)).decode()
        path = ws_url.split(f":{port}", 1)[1]
        self.sock.send((f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\n"
                        f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        self.buf = b""
        while b"\r\n\r\n" not in self.buf:
            self.buf += self.sock.recv(4096)
        self.buf = self.buf.split(b"\r\n\r\n", 1)[1]
        self.mid = 0
        self.errors = []
        for domain in ("Page", "Runtime", "Log"):
            self.call(f"{domain}.enable")

    def _recv_exact(self, n):
        while len(self.buf) < n:
            self.buf += self.sock.recv(65536)
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def _recv(self):
        _, b2 = self._recv_exact(2)
        n = b2 & 0x7F
        if n == 126:
            n = struct.unpack(">H", self._recv_exact(2))[0]
        elif n == 127:
            n = struct.unpack(">Q", self._recv_exact(8))[0]
        return json.loads(self._recv_exact(n))

    def _event(self, m):
        method, p = m.get("method"), m.get("params", {})
        if method == "Runtime.exceptionThrown":
            self.errors.append(str(p["exceptionDetails"].get("exception", {}).get("description", ""))[:300])
        elif method == "Runtime.consoleAPICalled" and p.get("type") == "error":
            self.errors.append(" ".join(str(a.get("value", a.get("description", ""))) for a in p.get("args", []))[:300])

    def call(self, method, **params):
        self.mid += 1
        data = json.dumps({"id": self.mid, "method": method, "params": params}).encode()
        mask, n = os.urandom(4), len(data)
        if n < 126:
            hdr = bytes([0x81, 0x80 | n])
        elif n < 65536:
            hdr = bytes([0x81, 0x80 | 126]) + struct.pack(">H", n)
        else:
            hdr = bytes([0x81, 0x80 | 127]) + struct.pack(">Q", n)
        self.sock.send(hdr + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))
        while True:
            m = self._recv()
            if m.get("id") == self.mid:
                return m.get("result", m)
            self._event(m)

    def js(self, expr):
        r = self.call("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True)
        return r.get("result", {}).get("value")

    def wait(self, expr, timeout=240):
        end = time.time() + timeout
        while time.time() < end:
            if self.js(expr):
                return True
            time.sleep(0.3)
        return False

    def screenshot(self, path):
        with open(path, "wb") as f:
            f.write(base64.b64decode(self.call("Page.captureScreenshot")["data"]))

    def close(self):
        self.proc.terminate()
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        shutil.rmtree(self.profile, ignore_errors=True)


def api_conversation_ids(api):
    try:
        with urllib.request.urlopen(f"{api}/api/chat/conversations/?scope=all&limit=200", timeout=10) as r:
            return {c["id"] for c in json.load(r).get("conversations", [])}
    except OSError:
        return set()


def api_delete(api, conv_id):
    req = urllib.request.Request(f"{api}/api/chat/conversations/{conv_id}/", method="DELETE")
    try:
        urllib.request.urlopen(req, timeout=10)
    except OSError:
        pass


# React-controlled textarea: set the value through the native setter so onChange fires.
SET_VALUE = """(sel, text) => {
  const el = document.querySelector(sel);
  const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
  setter.call(el, text);
  el.dispatchEvent(new Event('input', { bubbles: true }));
  return true;
}"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--app", default="http://127.0.0.1:5173")
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--shots", help="directory for screenshots (optional)")
    args = ap.parse_args()

    results = []

    def check(label, ok, detail=""):
        results.append(bool(ok))
        print(f"{'PASS' if ok else 'FAIL'}  {label}  {detail}".rstrip(), flush=True)

    def shot(name):
        if args.shots:
            os.makedirs(args.shots, exist_ok=True)
            b.screenshot(os.path.join(args.shots, f"{name}.png"))

    before = api_conversation_ids(args.api)
    b = Browser()
    try:
        b.call("Page.navigate", url=args.app)
        b.wait("!!document.querySelector('.composer-input')", 30)
        b.js("localStorage.removeItem('mrpl.lang'); localStorage.removeItem('mrpl.conversation'); true")
        b.call("Page.navigate", url=args.app)
        loaded = b.wait("!!document.querySelector('.composer-input')", 30)
        time.sleep(1)
        check("1. chat page loads without JavaScript errors", loaded and not b.errors, "; ".join(b.errors))

        # 2. Hindi interface
        b.js("[...document.querySelectorAll('.lang-toggle button')].find(x => x.lang === 'hi').click(); true")
        hindi = b.wait("document.documentElement.lang === 'hi' && document.querySelector('.new-chat-btn').innerText.includes('नई चैट')", 5)
        check("2. interface switches to Hindi", hindi,
              b.js("document.querySelector('.composer-input').placeholder"))
        shot("hindi-empty")

        # 3. Question in Hindi mode -> answer in Devanagari
        b.js(f"({SET_VALUE})('.composer-input', 'What is a centrifugal pump? Answer in two short sentences.')")
        b.js("document.querySelector('.send-btn').click(); true")
        done = b.wait("(() => { const m = [...document.querySelectorAll('.msg-assistant')].pop();"
                      " return m && m.classList.contains('is-done'); })()", 240)
        answer = b.js("[...document.querySelectorAll('.msg-assistant .msg-body')].pop()?.innerText || ''") or ""
        check("3. answer in Hindi mode is written in Devanagari",
              done and b.js(f"{DEVANAGARI}.test({json.dumps(answer)})"), answer[:80].replace("\n", " "))

        # 4. Screen-reader announcement
        check("4. 'Answer ready' announced (aria-live)",
              b.wait("document.querySelector('.chat-thread [role=status]')?.innerText.includes('उत्तर तैयार है')", 5))
        shot("hindi-answer")

        # 5. Edit the question
        has_edit = b.wait("!!document.querySelector('.msg-user-actions button')", 10)
        b.js("document.querySelector('.msg-user-actions button').click(); true")
        b.wait("!!document.querySelector('.msg-edit textarea')", 5)
        b.js(f"({SET_VALUE})('.msg-edit textarea', 'What is a gear pump? Answer in one short sentence.')")
        b.js("document.querySelector('.msg-edit .btn-primary').click(); true")
        edited = b.wait("(() => { const m = [...document.querySelectorAll('.msg-assistant')].pop();"
                        " return m && m.classList.contains('is-done'); })()", 240)
        counts = b.js("[document.querySelectorAll('.msg-user').length, document.querySelectorAll('.msg-assistant').length]")
        first_q = b.js("document.querySelector('.msg-user-bubble')?.innerText || ''")
        check("5. editing replaces the turn", has_edit and edited and counts == [1, 1] and "gear pump" in first_q,
              f"messages={counts}")

        # 6. Regenerate an earlier answer: ask a second question, then regenerate the first answer
        b.js(f"({SET_VALUE})('.composer-input', 'Name one use of it. One sentence.')")
        b.js("document.querySelector('.send-btn').click(); true")
        b.wait("document.querySelectorAll('.msg-assistant.is-done').length === 2", 240)
        b.js("window.confirm = () => true; true")
        clicked = b.js("(() => { const btn = [...document.querySelectorAll('.msg-assistant')][0]"
                       ".querySelector('.msg-actions button:nth-of-type(2)'); if (!btn) return false; btn.click(); return true; })()")
        regenerated = clicked and b.wait(
            "document.querySelectorAll('.msg-assistant').length === 1 && "
            "document.querySelector('.msg-assistant').classList.contains('is-done')", 240)
        check("6. regenerating an earlier answer drops the later turns", regenerated,
              f"assistant messages={b.js('document.querySelectorAll(\".msg-assistant\").length')}")

        # 7. Feedback
        b.js("document.querySelector('.msg-assistant .feedback-btn').click(); true")
        rated = b.wait("document.querySelector('.msg-assistant .feedback-btn').getAttribute('aria-pressed') === 'true'", 5)
        time.sleep(0.5)
        stored = False
        for conv_id in api_conversation_ids(args.api) - before:
            with urllib.request.urlopen(f"{args.api}/api/chat/conversations/{conv_id}/", timeout=10) as r:
                msgs = json.load(r)["conversation"]["messages"]
            stored = stored or any(m.get("feedback") == "up" for m in msgs)
        check("7. rating an answer is stored", rated and stored)

        # 8. Other pages in Hindi
        b.js("[...document.querySelectorAll('.nav-item')][1].click(); true")
        docs = b.wait("document.querySelector('.topbar-title')?.innerText === 'दस्तावेज़ सहायक' && !!document.querySelector('.documents-page')", 15)
        time.sleep(1)
        shot("hindi-documents")
        b.js("[...document.querySelectorAll('.nav-item')][2].click(); true")
        dash = b.wait("document.querySelector('#status-heading')?.innerText === 'सिस्टम स्थिति'", 15)
        b.wait("!document.querySelector('.status-pill.is-checking')", 20)
        shot("hindi-dashboard")
        check("8. Document Assistant and System Status render in Hindi", docs and dash)

        # 9. Dashboard content
        b.wait("!!document.querySelector('.trend svg')", 15)
        has = b.js("[!!document.querySelector('.trend svg rect.trend-bar'), document.querySelectorAll('.dash-table tbody tr').length,"
                   " [...document.querySelectorAll('.health-name')].some(e => e.innerText.includes('डेटाबेस')),"
                   " [...document.querySelectorAll('.health-name')].some(e => e.innerText.includes('डिस्क'))]")
        check("9. trend chart, per-model table, database and disk checks shown",
              has and has[0] and has[1] >= 3 and has[2] and has[3], str(has))

        # 10. OCR deep check (explicit button)
        b.js("document.querySelector('.deep-checks .dash-btn').click(); true")
        passed = b.wait("document.querySelector('.deep-checks li .status-pill')?.classList.contains('is-ready')", 180)
        detail = b.js("document.querySelector('.deep-checks li .health-detail, .deep-checks li .health-reason')?.innerText || ''")
        shot("hindi-dashboard-deep")
        check("10. OCR deep check passes", passed, detail)

        # 11. Back to English
        b.js("[...document.querySelectorAll('.lang-toggle button')].find(x => x.lang === 'en').click(); true")
        check("11. switching back to English", b.wait(
            "document.documentElement.lang === 'en' && document.querySelector('.new-chat-btn').innerText.includes('New chat')", 5))

        check("no JavaScript errors during the run", not b.errors, "; ".join(b.errors[:3]))
    finally:
        b.close()
        created = api_conversation_ids(args.api) - before
        for conv_id in created:
            api_delete(args.api, conv_id)
        if created:
            print(f"(removed {len(created)} conversation(s) created by this test)")

    failed = results.count(False)
    print(f"\n{len(results) - failed}/{len(results)} checks passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
