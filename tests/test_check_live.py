import os
import subprocess
import sys
import time

import check
from conftest import free_port, set_env, write

CHILD = "import os, sys, time; open(sys.argv[1], 'w').write(str(os.getpid())); time.sleep(60)"
PARENT = "import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', sys.argv[1], sys.argv[2]]); time.sleep(60)"
# a stand-in for doc-mcp / the bot: GET /health and POST /chat, on argv[1]; argv[2] = mcp_errors as JSON
STUB = """
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
class H(BaseHTTPRequestHandler):
    def reply(self, body):
        data = json.dumps(body).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(data)
    def do_GET(self):
        self.reply({"status": "ok", "mcp_errors": json.loads(sys.argv[2])})
    def do_POST(self):
        q = json.loads(self.rfile.read(int(self.headers["Content-Length"])))["input"]
        self.reply({"answer": "stub answer to " + q, "sources_md": "**Sources**"})
    def log_message(self, *a):
        pass
HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
"""


def alive(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def gone(pid: int, wait: float = 5) -> bool:
    deadline = time.monotonic() + wait
    while alive(pid):
        if time.monotonic() > deadline:
            return False
        time.sleep(0.1)
    return True


def stub(tmp_path, port, mcp_errors="[]"):
    proc = check.start([sys.executable, "-c", STUB, str(port), mcp_errors], tmp_path, tmp_path / f"stub{port}.log")
    assert check.wait_http(f"http://127.0.0.1:{port}/health", 10, proc)
    return proc


def test_stop_kills_child_processes(tmp_path):
    pid_file = tmp_path / "child.pid"
    proc = check.start([sys.executable, "-c", PARENT, CHILD, str(pid_file)], tmp_path, tmp_path / "p.log")
    deadline = time.monotonic() + 10
    while not (pid_file.exists() and pid_file.read_text()):
        assert time.monotonic() < deadline, "child never started"
        time.sleep(0.1)
    child = int(pid_file.read_text())
    check.stop(proc)
    assert gone(proc.pid) and gone(child)


def test_wait_http_true_when_up(tmp_path):
    port = free_port()
    proc = check.start([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"], tmp_path, tmp_path / "h.log")
    try:
        assert check.wait_http(f"http://127.0.0.1:{port}/", 10) is True
    finally:
        check.stop(proc)


def test_wait_http_false_on_timeout():
    assert check.wait_http(f"http://127.0.0.1:{free_port()}/", 1) is False


def test_wait_http_gives_up_when_process_exits(tmp_path):
    proc = check.start([sys.executable, "-c", "pass"], tmp_path, tmp_path / "x.log")
    began = time.monotonic()
    assert check.wait_http(f"http://127.0.0.1:{free_port()}/", 30, proc) is False
    assert time.monotonic() - began < 10


def test_offline_skips_pings(project, monkeypatch):
    def boom(p):
        raise AssertionError("pinged while offline")
    monkeypatch.setattr(check, "ping_completion", boom)
    monkeypatch.setattr(check, "ping_embedding", boom)
    assert check.main([str(project), "--offline"]) == 0


def test_pings_run_unless_offline(project, monkeypatch, capsys):
    monkeypatch.setattr(check, "ping_completion", lambda p: check.Result("completion model", "pass", "OK"))
    monkeypatch.setattr(check, "ping_embedding", lambda p: check.Result("embedding endpoint", "fail", "refused"))
    assert check.main([str(project)]) == 1
    out = capsys.readouterr().out
    assert "PASS completion model" in out and "FAIL embedding endpoint: refused" in out


def test_decision_ping_only_when_on(project, monkeypatch, capsys):
    monkeypatch.setattr(check, "ping_completion", lambda p: check.Result("completion model", "pass"))
    monkeypatch.setattr(check, "ping_embedding", lambda p: check.Result("embedding endpoint", "pass"))
    monkeypatch.setattr(check, "ping_decision", lambda p: check.Result("decision model", "pass", "0.97"))
    check.main([str(project)])
    assert "decision model" not in capsys.readouterr().out
    set_env(project, "bdc-assist", USE_DECISION_MODEL="true", DECISION_URL="https://x.services.ai.azure.com")
    write(project / "config/bdc-assist/prompts.yaml", 'decision_input_guardrail: "- Is `message` off topic?"\n'
                                                      "decision_output_guardrail: Is `answer` helpful?\n")
    check.main([str(project)])
    assert "PASS decision model: 0.97" in capsys.readouterr().out


def test_decision_ping_failure_reported(project, monkeypatch):
    def failed(clone, code, timeout=120):
        assert clone.name == "bdc-assist" and "get_decider" in code
        return subprocess.CompletedProcess([], 1, "", "Traceback ...\nopenai.NotFoundError: deployment not found\n")
    monkeypatch.setattr(check, "run_in_clone", failed)
    r = check.ping_decision(check.load_project(project))
    assert r.status == "fail" and "deployment not found" in r.detail


def test_ping_failure_reported(project, monkeypatch):
    def failed(clone, code, timeout=120):
        assert clone.name == "bdc-assist" and "get_llm" in code
        return subprocess.CompletedProcess([], 1, "", "Traceback ...\nAuthenticationError: bad key\n")
    monkeypatch.setattr(check, "run_in_clone", failed)
    r = check.ping_completion(check.load_project(project))
    assert r.status == "fail" and "bad key" in r.detail


def test_ping_timeout_reported(project, monkeypatch):
    def slow(clone, code, timeout=120):
        raise subprocess.TimeoutExpired(["uv"], timeout)
    monkeypatch.setattr(check, "run_in_clone", slow)
    r = check.ping_embedding(check.load_project(project))
    assert r.status == "fail" and "timed out" in r.detail


def test_live_stops_services_when_health_never_comes(project, monkeypatch, tmp_path):
    started, real_start = [], check.start

    def fake_start(cmd, cwd, log):
        started.append(real_start([sys.executable, "-c", "import time; time.sleep(60)"], tmp_path, log))
        return started[-1]
    monkeypatch.setattr(check, "start", fake_start)
    monkeypatch.setattr(check, "wait_http", lambda *a, **k: False)
    results = check.live_chat(check.load_project(project), "q", timeout=1)
    assert any(r.status == "fail" for r in results)
    assert started and all(gone(pr.pid) for pr in started)
    assert (project / "data/logs/bdc-doc-mcp.log").exists()


def test_live_chat_reuses_running_services(project, ports, monkeypatch, tmp_path):
    procs = [stub(tmp_path, ports[1]), stub(tmp_path, ports[0])]
    try:
        monkeypatch.setattr(check, "start", lambda *a: (_ for _ in ()).throw(AssertionError("started a service")))
        results = check.live_chat(check.load_project(project), "How do I log in?", timeout=10)
        assert [r.status for r in results if r.name == "live chat"] == ["pass"]
        assert "stub answer to How do I log in?" in " ".join(r.detail for r in results)
    finally:
        for proc in procs:
            check.stop(proc)


def test_live_chat_mcp_errors_fail(project, ports, tmp_path):
    procs = [stub(tmp_path, ports[1]), stub(tmp_path, ports[0], '["r_doc_mcp: connection refused"]')]
    try:
        results = check.live_chat(check.load_project(project), "q", timeout=10)
        assert "connection refused" in " ".join(r.detail for r in results if r.status == "fail")
    finally:
        for proc in procs:
            check.stop(proc)


def test_live_without_sample_questions_fails(project, monkeypatch, capsys):
    monkeypatch.setattr(check, "live_chat", lambda *a, **k: [check.Result("live chat", "pass")])
    assert check.main([str(project), "--offline", "--live"]) == 1
    assert "sample_questions.yaml" in capsys.readouterr().out
    write(project / "config/bdc-assist/sample_questions.yaml", "- How do I log in?\n")
    assert check.main([str(project), "--offline", "--live"]) == 0
