import socket
from pathlib import Path

import pytest
import yaml


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def write_yaml(path: Path, data) -> Path:
    return write(path, yaml.safe_dump(data, sort_keys=False))


def read_env(root: Path, repo: str) -> list[str]:
    return (root / repo / ".env").read_text(encoding="utf-8").splitlines()


def set_env(root: Path, repo: str, **kv: str) -> None:
    """Set keys in <root>/<repo>/.env, written raw: set_env(r, "x", A="   # c") gives the line 'A=   # c'."""
    lines = [l for l in read_env(root, repo) if l.split("=", 1)[0] not in kv]
    write(root / repo / ".env", "\n".join(lines + [f"{k}={v}" for k, v in kv.items()]) + "\n")


def env(**kv) -> str:
    return "".join(f"{k}={v}\n" for k, v in kv.items())


@pytest.fixture
def ports() -> tuple[int, int]:
    """(API_PORT, MCP_PORT), both free when picked."""
    return free_port(), free_port()


@pytest.fixture
def project(tmp_path, ports) -> Path:
    """A valid minimal project folder, under a name with a space, & and !."""
    api, mcp = ports
    root = tmp_path / "a b&c!"
    embed = {"EMBEDDING_MODEL_PROVIDER": "ollama", "EMBEDDING_URL": "http://localhost:11434", "EMBEDDING_MODEL": "bge-m3"}
    write(root / "bdc-assist/.env", env(CONFIG_DIR="../config/bdc-assist", API_PORT=api, COMPLETION_MODEL_PROVIDER="openai",
                                        COMPLETION_MODEL="gpt-4o-mini", OPENAI_API_KEY="sk-test"))
    write(root / "bdc-doc-mcp/.env", env(CONFIG_DIR="../config/bdc-doc-mcp", COLLECTION_NAME="demo", DB_PATH="../data/chroma",
                                         MCP_PORT=mcp, INGEST_TOKEN="tok-123", **embed))
    write(root / "bdc-doc-builder/.env", env(CONFIG_DIR="../config/bdc-doc-builder", DOC_MCP_URL=f"http://127.0.0.1:{mcp}",
                                             INGEST_TOKEN="tok-123", PREPROC_DATA_DIR="../data/build/",
                                             REPOS_DIR="../data/repos/", **embed))
    bot = root / "config/bdc-assist"
    write_yaml(bot / "project.yaml", {"name": "Demo", "short_name": "D", "assistant_name": "D Assist", "followups": 0})
    write(bot / "prompts.yaml", '# ${not_a_key} in a comment\nagent_system: "You are ${assistant_name}."\n')
    write(bot / "predefined_responses.yaml", "# no fixed answers\n")
    write_yaml(bot / "mcp_servers.yaml", {"r_doc_mcp": {"transport": "streamable_http", "url": f"http://127.0.0.1:{mcp}/mcp"}})
    write_yaml(root / "config/bdc-doc-mcp/doc_types.yaml", {"project": "Demo", "types": {"docs": {"description": "d", "default": True}}})
    write(root / "config/bdc-doc-mcp/prompts.yaml", "search_docs: Search the {project} docs.\n")
    builder = root / "config/bdc-doc-builder"
    write_yaml(builder / "sources.yaml", [{"source_type": "path", "doc_type": "docs", "link": "./docs"}])
    write(builder / "docs/intro.md", "# Intro\n")
    write(builder / "prompts.yaml", "summarize: '{text}'\n")
    write_yaml(builder / "build.yaml", {"chunk_size": 1500})
    return root
