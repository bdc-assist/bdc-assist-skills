import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values

import check
import envfile
from conftest import write

SCRIPT = Path(envfile.__file__)
TEMPLATE = ("# completion model\n"
            "COMPLETION_MODEL=gpt-4o-mini   # the model\n"
            "# COMPLETION_URL=              # endpoint for azure/vllm/ollama\n"
            "OPENAI_API_KEY=\n"
            "INGEST_TOKEN=change-me         # must match\n")


def run(*args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True)


def values(path: Path) -> dict:
    return dict(dotenv_values(path))


def test_set_starts_from_template_and_uncomments(tmp_path):
    write(tmp_path / "bdc-assist/.env.example", TEMPLATE)
    envfile.set_values(tmp_path, "bdc-assist", {"COMPLETION_MODEL": "gpt-4.1", "COMPLETION_URL": "http://x:1/v1"})
    text = (tmp_path / "bdc-assist/.env").read_text(encoding="utf-8")
    assert "COMPLETION_MODEL=gpt-4.1  # the model" in text
    assert "COMPLETION_URL=http://x:1/v1  # endpoint for azure/vllm/ollama" in text
    assert "# completion model" in text  # the template's comments stay
    assert values(tmp_path / "bdc-assist/.env")["COMPLETION_MODEL"] == "gpt-4.1"


def test_set_keeps_other_values_and_appends_new_keys(tmp_path):
    write(tmp_path / "bdc-assist/.env", "A=1\nB=2\n")
    envfile.set_values(tmp_path, "bdc-assist", {"B": "3", "C": "4"})
    assert values(tmp_path / "bdc-assist/.env") == {"A": "1", "B": "3", "C": "4"}


def test_empty_value_drops_the_comment(tmp_path):
    write(tmp_path / "bdc-doc-mcp/.env.example", TEMPLATE)
    envfile.set_values(tmp_path, "bdc-doc-mcp", {"INGEST_TOKEN": ""})
    lines = (tmp_path / "bdc-doc-mcp/.env").read_text(encoding="utf-8").splitlines()
    assert "INGEST_TOKEN=" in lines and not any(check.COMMENT_AS_VALUE.match(l) for l in lines)


def test_value_with_spaces_or_hash_is_quoted(tmp_path):
    envfile.set_values(tmp_path, "bdc-assist", {"A": "a b", "B": "x#y"})
    assert values(tmp_path / "bdc-assist/.env") == {"A": "a b", "B": "x#y"}


def test_output_masks_secrets(tmp_path):
    write(tmp_path / "bdc-assist/.env", "OPENAI_API_KEY=sk-old-secret\n")
    done = run("set", tmp_path, "bdc-assist", "OPENAI_API_KEY=sk-new-secret", "COMPLETION_MODEL=gpt-4.1")
    assert done.returncode == 0, done.stderr
    assert "secret" not in done.stdout
    assert "OPENAI_API_KEY: *** -> ***" in done.stdout and "COMPLETION_MODEL: (unset) -> gpt-4.1" in done.stdout


def test_dry_run_writes_nothing(tmp_path):
    write(tmp_path / "bdc-assist/.env", "A=1\n")
    done = run("set", tmp_path, "bdc-assist", "A=2", "--dry-run")
    assert done.returncode == 0 and "A: 1 -> 2" in done.stdout
    assert values(tmp_path / "bdc-assist/.env") == {"A": "1"}


def test_server_and_deploy_targets(tmp_path):
    envfile.set_values(tmp_path, "server:bdc-assist", {"CORS_ORIGINS": "https://a.example.org"})
    assert values(tmp_path / "deploy/bdc-assist.env.server") == {"CORS_ORIGINS": "https://a.example.org"}
    envfile.set_values(tmp_path, "deploy", {"API_PORT": "9000"})
    assert values(tmp_path / "deploy/.env") == {"API_PORT": "9000", "BUILD_FLAGS": ""}  # from the skill's template


def test_dollar_in_a_value_warns(tmp_path):
    # python-dotenv expands ${...} even in quotes, docker expands $NAME: the value may not read back as written
    done = run("set", tmp_path, "bdc-assist", "OPENAI_API_KEY=ab${cd}ef", "COMPLETION_MODEL=gpt-4o-mini")
    assert done.returncode == 0 and "OPENAI_API_KEY" in done.stderr and "$" in done.stderr
    assert "ab${cd}ef" not in done.stderr + done.stdout  # still never printed
    assert "COMPLETION_MODEL" not in done.stderr


def test_unknown_target_fails(tmp_path):
    done = run("set", tmp_path, "nope", "A=1")
    assert done.returncode != 0 and "target" in done.stderr


def test_token_set_once_and_kept(tmp_path):
    for repo in ("bdc-doc-mcp", "bdc-doc-builder"):
        write(tmp_path / f"{repo}/.env.example", TEMPLATE)
    first = run("token", tmp_path)
    assert first.returncode == 0, first.stderr
    token = values(tmp_path / "bdc-doc-mcp/.env")["INGEST_TOKEN"]
    assert token and token != "change-me" and token == values(tmp_path / "bdc-doc-builder/.env")["INGEST_TOKEN"]
    assert token not in first.stdout
    again = run("token", tmp_path)
    assert values(tmp_path / "bdc-doc-mcp/.env")["INGEST_TOKEN"] == token and "kept" in again.stdout


def test_server_token_differs_from_local(tmp_path):
    envfile.token(tmp_path)
    envfile.token(tmp_path, server=True)
    local = values(tmp_path / "bdc-doc-mcp/.env")["INGEST_TOKEN"]
    server = values(tmp_path / "deploy/bdc-doc-mcp.env.server")["INGEST_TOKEN"]
    assert server and server != local and server == values(tmp_path / "deploy/bdc-doc-builder.env.server")["INGEST_TOKEN"]


def test_run_gives_a_program_the_target_values(tmp_path):
    write(tmp_path / "deploy/bdc-doc-builder.env.server", "INGEST_TOKEN=server-tok\nDOC_MCP_URL=http://127.0.0.1:18001\n")
    done = run("run", tmp_path, "server:bdc-doc-builder", "--", sys.executable, "-c",
               "import os; print(os.environ['DOC_MCP_URL'], os.environ['INGEST_TOKEN'] == 'server-tok')")
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "http://127.0.0.1:18001 True"


def test_run_passes_the_exit_code(tmp_path):
    write(tmp_path / "deploy/bdc-doc-builder.env.server", "A=1\n")
    assert run("run", tmp_path, "server:bdc-doc-builder", "--", sys.executable, "-c", "raise SystemExit(3)").returncode == 3
