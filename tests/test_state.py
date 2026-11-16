import json
import subprocess
import sys
from pathlib import Path

import yaml

import state

SCRIPT = Path(state.__file__)
CLEAN = {"edited": [], "missing": [], "template_changed": []}


def write(root: Path, rel: str, text: str, newline: str = "\n") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.replace("\n", newline).encode())
    return path


def test_record_then_status_clean(tmp_path):
    write(tmp_path, "config/x.yaml", "a: 1\n")
    state.record(tmp_path, {"config/x.yaml": None})
    assert state.status(tmp_path) == CLEAN


def test_hand_edit_is_edited(tmp_path):
    path = write(tmp_path, "config/x.yaml", "a: 1\n")
    state.record(tmp_path, {"config/x.yaml": None})
    path.write_text("a: 1\nb: 2\n")
    assert state.status(tmp_path)["edited"] == ["config/x.yaml"]


def test_crlf_only_change_is_not_edited(tmp_path):
    write(tmp_path, "config/x.yaml", "a: 1\nb: 2\n")
    state.record(tmp_path, {"config/x.yaml": None})
    write(tmp_path, "config/x.yaml", "a: 1\nb: 2\n", newline="\r\n")
    assert state.status(tmp_path)["edited"] == []


def test_deleted_file_is_missing(tmp_path):
    path = write(tmp_path, "config/x.yaml", "a: 1\n")
    state.record(tmp_path, {"config/x.yaml": None})
    path.unlink()
    assert state.status(tmp_path) == {**CLEAN, "missing": ["config/x.yaml"]}


def test_template_change_reported(tmp_path):
    write(tmp_path, "config/p.yaml", "prompt: x\n")
    template = write(tmp_path, "bdc-doc-mcp/config/prompts.yaml", "prompt: x\n")
    state.record(tmp_path, {"config/p.yaml": "bdc-doc-mcp/config/prompts.yaml"})
    template.write_text("prompt: y\n")
    assert state.status(tmp_path) == {**CLEAN, "template_changed": ["config/p.yaml"]}


def test_record_again_clears_and_keeps_others(tmp_path):
    a = write(tmp_path, "config/a.yaml", "a: 1\n")
    write(tmp_path, "config/b.yaml", "b: 1\n")
    state.record(tmp_path, {"config/a.yaml": None, "config/b.yaml": None})
    a.write_text("a: 2\n")
    state.record(tmp_path, {"config/a.yaml": None})
    assert state.status(tmp_path) == CLEAN
    written = yaml.safe_load((tmp_path / ".bdc-assist-config/written.yaml").read_text())
    assert set(written["files"]) == {"config/a.yaml", "config/b.yaml"}


def test_record_keeps_the_template_when_none_given(tmp_path):
    # bdc-assist-custom re-records project.yaml without its template; the template link must survive
    write(tmp_path, "config/p.yaml", "a: 1\n")
    template = write(tmp_path, "bdc-assist/config/project.yaml", "a: 1\n")
    state.record(tmp_path, {"config/p.yaml": "bdc-assist/config/project.yaml"})
    write(tmp_path, "config/p.yaml", "a: 2\n")
    state.record(tmp_path, {"config/p.yaml": None})
    template.write_text("a: 3\n")
    assert state.status(tmp_path) == {**CLEAN, "template_changed": ["config/p.yaml"]}


def test_record_env_flag_records_env_files_without_naming_them(tmp_path):
    write(tmp_path, "bdc-assist/.env.example", "A=\n")
    write(tmp_path, "bdc-assist/.env", "A=1\n")
    write(tmp_path, "bdc-doc-mcp/.env", "B=1\n")
    write(tmp_path, "deploy/.env", "API_PORT=8010\n")
    write(tmp_path, "deploy/bdc-assist.env.server", "C=1\n")
    write(tmp_path, "config/x.yaml", "a: 1\n")
    rec = subprocess.run([sys.executable, str(SCRIPT), "record", str(tmp_path), "config/x.yaml", "--env"],
                         capture_output=True, text=True)
    assert rec.returncode == 0, rec.stderr
    files = yaml.safe_load((tmp_path / ".bdc-assist-config/written.yaml").read_text())["files"]
    assert set(files) == {"config/x.yaml", "bdc-assist/.env", "bdc-doc-mcp/.env", "deploy/.env",
                          "deploy/bdc-assist.env.server"}
    assert files["bdc-assist/.env"]["template"] == "bdc-assist/.env.example"
    assert files["bdc-doc-mcp/.env"]["template"] is None


def test_cli_status_prints_json(tmp_path):
    write(tmp_path, "config/x.yaml", "a: 1\n")
    rec = subprocess.run([sys.executable, str(SCRIPT), "record", str(tmp_path), "config/x.yaml"],
                         capture_output=True, text=True)
    assert rec.returncode == 0, rec.stderr
    out = subprocess.run([sys.executable, str(SCRIPT), "status", str(tmp_path)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == CLEAN
