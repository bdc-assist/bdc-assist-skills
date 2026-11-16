# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml", "python-dotenv"]
# ///
"""Check a bdc-assist-init project folder: config files, cross-repo settings, custom code names,
sources and ports (static); model endpoints (unless --offline); one real chat (--live).

  uv run check.py <project> [--offline] [--live]

Prints PASS / WARN / FAIL per check, with a fix under each failure; exits 1 if anything failed.
"""
import argparse
import ast
import json
import os
import re
import signal
import socket
import string
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import yaml
from dotenv import dotenv_values

REPOS = ("bdc-assist", "bdc-doc-mcp", "bdc-doc-builder")
REQUIRED = {"bdc-assist": ["project.yaml", "prompts.yaml", "predefined_responses.yaml", "mcp_servers.yaml"],
            "bdc-doc-mcp": ["doc_types.yaml", "prompts.yaml"],
            "bdc-doc-builder": ["sources.yaml", "prompts.yaml", "build.yaml"]}
EMBEDDING_KEYS = ("EMBEDDING_MODEL_PROVIDER", "EMBEDDING_URL", "EMBEDDING_MODEL")
DEFAULT_MCP_PORT, DEFAULT_API_PORT = 8001, 8010
BUILDER_DEFAULT_URL = "http://127.0.0.1:8001"  # bdc-doc-builder's own DOC_MCP_URL default (8001 since its PR #7)
# KEY= with nothing but spaces before a comment: python-dotenv reads it as empty, docker's env_file as "# ..."
COMMENT_AS_VALUE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*#")
URL = re.compile(r"^[a-z][a-z0-9+.-]*://", re.I)


@dataclass
class Result:
    name: str
    status: Literal["pass", "warn", "fail"]
    detail: str = ""
    fix: str = ""


@dataclass
class Project:
    root: Path
    env: dict[str, dict[str, str | None]]  # repo -> its .env, as python-dotenv reads it
    config: dict[str, Path | None]  # repo -> CONFIG_DIR resolved against the clone folder


def load_project(root: Path) -> Project:
    root = Path(root).resolve()
    env, config = {}, {}
    for repo in REPOS:
        path = root / repo / ".env"
        env[repo] = dict(dotenv_values(path)) if path.is_file() else {}
        config_dir = env[repo].get("CONFIG_DIR")
        config[repo] = (root / repo / config_dir).resolve() if config_dir else None
    return Project(root, env, config)


class _UniqueKeys(yaml.SafeLoader):
    """bdc-assist's own loader (r_assist/prompts.py): a key written twice in one mapping fails."""


def _mapping(loader, node, deep=False):
    keys = [loader.construct_object(k, deep=deep) for k, _ in node.value]
    if dup := next((k for k in keys if keys.count(k) > 1), None):
        raise yaml.constructor.ConstructorError(None, None, f"{dup!r} written twice: give it once, with "
                                                "everything under it", node.start_mark)
    return loader.construct_mapping(node, deep)


_UniqueKeys.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)

# chromadb's rule for a collection name: 3-512 of [a-zA-Z0-9._-], starting and ending with a letter or digit
COLLECTION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,510}[A-Za-z0-9]$")


def _yaml(path: Path):
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeys) or {}


def _int(value, default: int) -> int | None:
    try:
        return int(value) if value else default
    except ValueError:
        return None


def check_files(p: Project) -> list[Result]:
    out = []
    for repo in REPOS:
        clone, problems = p.root / repo, []
        if not clone.is_dir():
            problems.append(f"no clone at {clone}")
        elif not (clone / ".env").is_file():
            problems.append(f"no {repo}/.env")
        elif not p.config[repo]:
            problems.append(f"CONFIG_DIR is not set in {repo}/.env")
        elif not p.config[repo].is_dir():
            problems.append(f"CONFIG_DIR folder {p.config[repo]} does not exist")
        else:
            problems += [f"missing {p.config[repo] / f}" for f in REQUIRED[repo] if not (p.config[repo] / f).is_file()]
            problems += _unparsable(p.config[repo], repo)
        out.append(Result(f"files {repo}", "fail", "; ".join(problems),
                          "write the file (re-run bdc-assist-init), or quote the value the parser stops at "
                          "(a ': ' or ' #' inside a plain value)")
                   if problems else Result(f"files {repo}", "pass"))
    return out


def _yaml_problem(e: yaml.YAMLError) -> str:
    mark = getattr(e, "problem_mark", None) or getattr(e, "context_mark", None)
    return (f"line {mark.line + 1}: " if mark else "") + str(getattr(e, "problem", None) or e)


# the yaml each service reads from its config folder (the builder also reads what sources.yaml links: check_sources)
SERVICE_READS = {repo: REQUIRED[repo] + (["sample_questions.yaml"] if repo == "bdc-assist" else []) for repo in REPOS}
LISTS = ("sources.yaml", "sample_questions.yaml")  # every other one is a mapping


def _unparsable(config: Path, repo: str) -> list[str]:
    """The yaml files a service reads that don't parse (bdc-assist's rules: no key twice) or aren't the right shape."""
    bad = []
    for name in SERVICE_READS[repo]:
        path = config / name
        if not path.is_file():
            continue
        try:
            data = _yaml(path)
        except yaml.YAMLError as e:
            bad.append(f"{name} {_yaml_problem(e)}")
            continue
        want = list if name in LISTS else dict
        if data and not isinstance(data, want):
            bad.append(f"{name} must be a {'list (- lines)' if want is list else 'mapping (key: value lines)'}")
    return bad


def _env_comments(p: Project) -> list[Result]:
    files = [p.root / repo / ".env" for repo in REPOS] + sorted((p.root / "deploy").glob("*.env.server"))
    bad = [f"{f.relative_to(p.root).as_posix()}: {m.group(1)}" for f in files if f.is_file()
           for line in f.read_text(encoding="utf-8").splitlines() if (m := COMMENT_AS_VALUE.match(line))]
    if bad:
        return [Result("env comments", "fail",
                       "an empty value followed by a comment (docker reads the comment as the value; python as empty): "
                       + ", ".join(bad), "write the value, or delete the line")]
    return [Result("env comments", "pass")]


def _token(name: str, mcp: dict, builder: dict, where: str, fix: str) -> Result:
    tokens = mcp.get("INGEST_TOKEN"), builder.get("INGEST_TOKEN")
    if not all(tokens) or tokens[0] != tokens[1] or "change-me" in tokens:
        return Result(name, "fail", f"INGEST_TOKEN must be set, the same in {where}, and not the example 'change-me'", fix)
    return Result(name, "pass")


def _embedding(name: str, mcp: dict, builder: dict, where: str) -> Result:
    # the URL is read only by self-hosted and Azure providers; openai (and fake) ignore it
    need = ["EMBEDDING_MODEL_PROVIDER", "EMBEDDING_MODEL"]
    if (mcp.get("EMBEDDING_MODEL_PROVIDER") or "").lower() in ("vllm", "ollama", "azure"):
        need.append("EMBEDDING_URL")
    differ = list(dict.fromkeys([k for k in need if not mcp.get(k)] +
                                [k for k in EMBEDDING_KEYS if mcp.get(k) != builder.get(k)]))
    if differ:
        return Result(name, "fail", f"{', '.join(differ)} must be set and the same in {where} "
                      "(queries and documents need one model)", "copy the values from one file to the other")
    if mcp["EMBEDDING_MODEL_PROVIDER"] == "fake":
        return Result(name, "warn", "EMBEDDING_MODEL_PROVIDER=fake: hash vectors, for tests only")
    return Result(name, "pass")


def _collection(name: str, env: dict, where: str) -> list[Result]:
    value = env.get("COLLECTION_NAME")
    if value and not COLLECTION.match(value) or value and ".." in value:
        return [Result(name, "fail", f"COLLECTION_NAME={value} in {where}: the search database needs 3 or more of "
                       "letters, digits, '.', '_', '-', starting and ending with a letter or digit",
                       f"for example COLLECTION_NAME={re.sub(r'[^A-Za-z0-9]+$', '', value.lower()) or 'my'}-docs")]
    return []


def check_agreement(p: Project) -> list[Result]:
    out = _env_comments(p)
    mcp, builder, bot = p.env["bdc-doc-mcp"], p.env["bdc-doc-builder"], p.env["bdc-assist"]
    out.append(_token("ingest token", mcp, builder, "bdc-doc-mcp/.env and bdc-doc-builder/.env",
                      'envfile.py token "<project>" writes a shared one'))
    out.append(_embedding("embedding model", mcp, builder, "bdc-doc-mcp/.env and bdc-doc-builder/.env"))
    out += _collection("collection name", mcp, "bdc-doc-mcp/.env")

    port = _int(mcp.get("MCP_PORT"), DEFAULT_MCP_PORT)
    if port is None:
        return out + [Result("doc-mcp port", "fail", f"MCP_PORT={mcp['MCP_PORT']!r} is not a number", "set MCP_PORT=8001")]

    url = builder.get("DOC_MCP_URL") or BUILDER_DEFAULT_URL
    if urlsplit(url).port != port:
        out.append(Result("builder -> doc-mcp", "fail", f"bdc-doc-builder DOC_MCP_URL={url} is not doc-mcp's MCP_PORT {port}",
                          f"set DOC_MCP_URL=http://127.0.0.1:{port} in bdc-doc-builder/.env"))
    else:
        out.append(Result("builder -> doc-mcp", "pass"))

    servers_file = p.config["bdc-assist"] / "mcp_servers.yaml"
    server = (_yaml(servers_file).get("r_doc_mcp") or {}) if servers_file.is_file() else {}
    server = server if isinstance(server, dict) else {}  # e.g. "r_doc_mcp: http://...": no url: key
    url = bot.get("R_DOC_MCP_URL") or server.get("url") or ""
    where = "R_DOC_MCP_URL in bdc-assist/.env" if bot.get("R_DOC_MCP_URL") else "r_doc_mcp url in mcp_servers.yaml"
    parts = urlsplit(url)
    if parts.port != port or parts.path.rstrip("/") != "/mcp":
        out.append(Result("bot -> doc-mcp", "fail", f"{where} ({url or 'missing'}) must be doc-mcp's /mcp on port {port}",
                          f"set r_doc_mcp url: http://127.0.0.1:{port}/mcp"))
    else:
        out.append(Result("bot -> doc-mcp", "pass"))
    return out


def _strings(data):
    if isinstance(data, str):
        yield data
    elif isinstance(data, dict):
        for v in data.values():
            yield from _strings(v)
    elif isinstance(data, list):
        for v in data:
            yield from _strings(v)


# the prompts bdc-assist .format()s, with the slots it fills: any other {name}, or a lone brace, fails
# (at startup for agent_system, on every chat for the others). A node's own prompts have their own slots.
FORMATTED = {"agent_system": {"date", "tools"}, "input_guardrail_human": {"input"},
             "output_guardrail_human": {"input", "answer"}, "suggest_followups_human": {"input", "answer"},
             "topic_classifier_system": {"topics"}, "sources": {"items"},
             "sources_item": {"title", "link", "type"}, "sources_item_no_link": {"title", "type"}}


def _slot_problems(texts: dict) -> list[str]:
    out = []
    for key, allowed in FORMATTED.items():
        if not isinstance(texts.get(key), str):
            continue
        text = re.sub(r"\$\{[^}]*\}", "", texts[key].replace("$$", ""))  # ${...} is filled before .format()
        try:
            fields = [f for _, f, _, _ in string.Formatter().parse(text) if f is not None]
        except ValueError as e:
            out.append(f"prompts.yaml [{key}]: {e}")
            continue
        out += [f"prompts.yaml [{key}]: {{{f}}}" for f in dict.fromkeys(fields)
                if re.split(r"[.\[]", f)[0] not in allowed]
    return out


def check_placeholders(p: Project) -> list[Result]:
    """Like bdc-assist's prompts._fill: a ${key} that isn't a project.yaml key fails its startup; and a
    {slot} or brace .format() can't fill (FORMATTED)."""
    config = p.config["bdc-assist"]
    keys = set(_yaml(config / "project.yaml"))
    unknown = []
    for name in ("prompts.yaml", "predefined_responses.yaml", "mcp_servers.yaml"):
        for s in _strings(_yaml(config / name)):
            unknown += [f"{name}: {m.group()}" for m in re.finditer(r"\$\{([^}]*)\}?", s.replace("$$", ""))
                        if m.group(1) not in keys]
    out = []
    if unknown:
        out.append(Result("placeholders", "fail", "unknown placeholder " + ", ".join(dict.fromkeys(unknown)),
                          f"fix the name, or add the key to {config / 'project.yaml'}"))
    if slots := _slot_problems(_yaml(config / "prompts.yaml")):
        out.append(Result("prompt slots", "fail", "not a slot bdc-assist fills: " + ", ".join(slots),
                          "write a literal brace twice: {{ and }}"))
    return out or [Result("placeholders", "pass")]


def _defined(path: Path) -> set[str]:
    names = set()
    for node in ast.parse(path.read_text(encoding="utf-8"), filename=str(path)).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names |= {t.id for t in targets if isinstance(t, ast.Name)}
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names |= {(a.asname or a.name).split(".")[0] for a in node.names}
    return names


def check_custom_names(p: Project) -> list[Result]:
    config = p.config["bdc-assist"]
    problems = []
    slots = _yaml(config / "project.yaml").get("extra_nodes") or {}
    if not isinstance(slots, dict):
        problems.append("extra_nodes in project.yaml must be a mapping of before_agent / after_agent / after_finish "
                        "to {name: settings}")
        slots = {}
    wanted = {"interceptors.py": [n for s in _yaml(config / "mcp_servers.yaml").values() if isinstance(s, dict)
                                  for n in s.get("interceptors") or []],
              "nodes.py": [n for names in slots.values() for n in (names or {})]}
    for file, names in wanted.items():
        if not names:
            continue
        path = config / file
        if not path.is_file():
            problems.append(f"{', '.join(names)} named in yaml, but there is no {path}")
            continue
        try:
            defined = _defined(path)
        except SyntaxError as e:
            problems.append(f"{file} line {e.lineno}: {e.msg}")
            continue
        problems += [f"no {n} in {file}" for n in names if n not in defined]
    if problems:
        return [Result("custom code", "fail", "; ".join(problems), "write the function, or remove its name from the yaml "
                       "(bdc-assist-custom builds them)")]
    return [Result("custom code", "pass")]


def _source_paths(sources: Path, seen: set[Path], bad: list[str]):
    """(link as written, resolved path, file listing it) of each local source, following yaml includes.
    An included file that doesn't parse, or an entry that isn't a mapping, goes in bad."""
    if sources in seen or not sources.is_file():
        return
    seen.add(sources)
    try:
        entries = _yaml(sources) or []
    except yaml.YAMLError as e:
        bad.append(f"{sources.name} {_yaml_problem(e)}")
        return
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            bad.append(f"{sources.name}: an entry that isn't a mapping ({entry!r})")
            continue
        link = str(entry.get("link") or "")
        if entry.get("source_type") not in ("path", "yaml", "transcripts") or not link or URL.match(link):
            continue
        path = (sources.parent / link.split("#")[0]).resolve()
        yield link, path, sources
        if entry["source_type"] in ("yaml", "transcripts") and path.is_file():
            if entry["source_type"] == "yaml":
                yield from _source_paths(path, seen, bad)
            else:  # a transcripts list: the builder reads it too
                try:
                    _yaml(path)
                except yaml.YAMLError as e:
                    bad.append(f"{path.name} {_yaml_problem(e)}")


def check_sources(p: Project) -> list[Result]:
    missing, outside, bad = [], [], []
    for link, path, listed_in in _source_paths(p.config["bdc-doc-builder"] / "sources.yaml", set(), bad):
        where = f"{link} (in {listed_in.name})"
        if not path.exists():
            missing.append(where)
        elif (p.root / "deploy/docker-compose.yml").is_file() and not path.is_relative_to(p.root):
            outside.append(where)
    out = []
    if bad:
        out.append(Result("sources", "fail", "; ".join(bad), "fix the file (quote a value holding ': ' or ' #')"))
    if missing:
        out.append(Result("sources", "fail", "local source not found: " + ", ".join(missing),
                          "fix the link (relative links resolve against the file that lists them)"))
    if outside:
        out.append(Result("sources", "warn", "outside the project folder: " + ", ".join(outside),
                          "the server's builder can't read it; move it under the project folder"))
    return out or [Result("sources", "pass")]


LIST_ITEM = re.compile(r"^\s*[-*]\s([^\n]+)$", re.M)  # what langchain's MarkdownListOutputParser takes


def _decision_on(env: dict) -> bool:
    # as bdc-assist's config.USE_DECISION_MODEL reads it
    return (env.get("USE_DECISION_MODEL") or "").split("#")[0].strip().lower() == "true"


def _decision_url(env: dict) -> bool:
    """Decision-1's Azure resource: DECISION_URL's host, else COMPLETION_URL's or OPENAI_BASE_URL's."""
    return bool(urlsplit(env.get("DECISION_URL") or env.get("COMPLETION_URL") or env.get("OPENAI_BASE_URL") or "").netloc)


def check_decision(p: Project) -> list[Result]:
    """USE_DECISION_MODEL=true: what bdc-assist's build_graph refuses at startup without."""
    bot = p.env["bdc-assist"]
    if not _decision_on(bot):
        return []
    config = p.config["bdc-assist"]
    texts, topics = _yaml(config / "prompts.yaml"), _yaml(config / "predefined_responses.yaml")
    need = ["decision_input_guardrail", "decision_output_guardrail"] + (["decision_classify"] if topics else [])
    problems = []
    if missing := [k for k in need if not texts.get(k)]:
        problems.append(f"prompts.yaml has no {', '.join(missing)}")
    if texts.get("decision_input_guardrail") and not LIST_ITEM.findall(str(texts["decision_input_guardrail"])):
        problems.append("decision_input_guardrail must be one '- ' question per line, each phrased so yes means block")
    if any(str(t).strip().lower() == "other" for t in topics):
        problems.append('no predefined topic may be named "other": Decision-1 picks it for a question about none of them')
    if not _decision_url(bot):
        problems.append("no DECISION_URL in bdc-assist/.env (nor a COMPLETION_URL or OPENAI_BASE_URL to take its host from)")
    if problems:
        return [Result("decision model", "fail", "USE_DECISION_MODEL=true, but " + "; ".join(problems),
                       "add what's missing (config-map.md, decision model), or set USE_DECISION_MODEL=false")]
    return [Result("decision model", "pass")]


def check_deploy_choice(p: Project) -> list[Result]:
    """A setup picks one deployment: docker or Kubernetes."""
    deploy = p.root / "deploy"
    if (deploy / "docker-compose.yml").is_file() and (deploy / "k8s").is_dir():
        return [Result("deployment choice", "fail", "pick one deployment: docker or Kubernetes, not both",
                       "remove deploy/docker-compose.yml or deploy/k8s/")]
    return []


def check_server(p: Project) -> list[Result]:
    """With a server deployment (deploy/docker-compose.yml or deploy/k8s/): its three .env.server files exist
    and agree, as the clones' .env files must, and the bot names real browser origins."""
    deploy = p.root / "deploy"
    if not ((deploy / "docker-compose.yml").is_file() or (deploy / "k8s").is_dir()):
        return []
    paths = {repo: deploy / f"{repo}.env.server" for repo in REPOS}
    missing = [f"deploy/{path.name}" for path in paths.values() if not path.is_file()]
    if missing:
        return [Result("server env", "fail", "missing " + ", ".join(missing), "re-run bdc-assist-init's server step")]
    env = {repo: dict(dotenv_values(path)) for repo, path in paths.items()}
    pair = "deploy/bdc-doc-mcp.env.server and deploy/bdc-doc-builder.env.server"
    out = [_token("server ingest token", env["bdc-doc-mcp"], env["bdc-doc-builder"], pair,
                  'envfile.py token "<project>" --server writes a shared one'),
           _embedding("server embedding model", env["bdc-doc-mcp"], env["bdc-doc-builder"], pair)]
    out += _collection("server collection name", env["bdc-doc-mcp"], "deploy/bdc-doc-mcp.env.server")
    cors = [o.strip() for o in (env["bdc-assist"].get("CORS_ORIGINS") or "").split(",") if o.strip()]
    if not cors or "*" in cors:
        out.append(Result("server CORS_ORIGINS", "fail", "deploy/bdc-assist.env.server needs CORS_ORIGINS: the real "
                          "site origins that call the bot, never *", "envfile.py set \"<project>\" server:bdc-assist "
                          "CORS_ORIGINS=https://your-site.example.org"))
    else:
        out.append(Result("server CORS_ORIGINS", "pass"))
    if _decision_on(env["bdc-assist"]) and not _decision_url(env["bdc-assist"]):
        out.append(Result("server decision model", "fail", "deploy/bdc-assist.env.server has USE_DECISION_MODEL=true "
                          "but no DECISION_URL (nor a COMPLETION_URL or OPENAI_BASE_URL)",
                          "envfile.py set \"<project>\" server:bdc-assist DECISION_URL=https://<name>.services.ai.azure.com"))
    return out


THIS_MACHINE = ("localhost", "127.0.0.1", "0.0.0.0", "host.docker.internal")
MODEL_URLS = ("COMPLETION_URL", "OPENAI_BASE_URL", "DECISION_URL", "EMBEDDING_URL")


def check_k8s(p: Project) -> list[Result]:
    """The Kubernetes drafts in deploy/k8s/: every fill-in filled, every file parses, doc-mcp stays one copy;
    and the cluster-side model URLs aren't this machine's."""
    folder = p.root / "deploy" / "k8s"
    if not folder.is_dir():
        return []
    problems, docs = [], []
    for path in sorted(folder.glob("*.y*ml")):
        text = path.read_text(encoding="utf-8")
        if left := sorted(set(re.findall(r"\$\{\w+\}", text))):
            problems.append(f"{path.name}: fill-ins left: {', '.join(left)}")
        try:
            docs += [d for d in yaml.safe_load_all(text) if isinstance(d, dict)]
        except yaml.YAMLError as e:
            problems.append(f"{path.name} {_yaml_problem(e)}")
    for d in docs:
        if d.get("kind") == "Deployment" and (d.get("metadata") or {}).get("name") == "doc-mcp" \
                and (d.get("spec") or {}).get("replicas", 1) != 1:
            problems.append("doc-mcp needs replicas: 1, since one process must own the search database")
    out = [Result("kubernetes", "fail", "; ".join(problems), "fill in or fix the drafts in deploy/k8s/")
           if problems else Result("kubernetes", "pass")]
    near = []
    for repo in ("bdc-assist", "bdc-doc-mcp"):  # these run in the cluster; the builder runs here, port-forwarded
        path = p.root / "deploy" / f"{repo}.env.server"
        env = dotenv_values(path) if path.is_file() else {}
        near += [f"{path.name} {k}" for k in MODEL_URLS if urlsplit(env.get(k) or "").hostname in THIS_MACHINE]
    if near:
        out.append(Result("kubernetes model URLs", "fail", "pointing at this machine, which a cluster can't reach: "
                          + ", ".join(near), "use an address the cluster can reach"))
    return out


def _listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def check_ports(p: Project) -> list[Result]:
    out = []
    for name, port in (("doc-mcp", _int(p.env["bdc-doc-mcp"].get("MCP_PORT"), DEFAULT_MCP_PORT)),
                       ("bot", _int(p.env["bdc-assist"].get("API_PORT"), DEFAULT_API_PORT))):
        if port and _listening(port):
            out.append(Result(f"port {port}", "warn", f"something is listening on {port} ({name}'s port)",
                              "if it isn't this project's service, stop it"))
        else:
            out.append(Result(f"port {port}", "pass"))
    return out


def run_in_clone(clone: Path, code: str, timeout: float = 120) -> subprocess.CompletedProcess:
    # cwd = the clone, as the services run: its .env and its relative CONFIG_DIR resolve the same way
    return subprocess.run(["uv", "run", "python", "-c", code], cwd=clone, capture_output=True, text=True, timeout=timeout)


def _ping(p: Project, name: str, repo: str, code: str, fix: str) -> Result:
    try:
        done = run_in_clone(p.root / repo, code)
    except subprocess.TimeoutExpired:
        return Result(name, "fail", "timed out", fix)
    if done.returncode != 0:
        lines = (done.stderr or done.stdout or "").strip().splitlines()
        return Result(name, "fail", lines[-1] if lines else f"exit code {done.returncode}", fix)
    return Result(name, "pass", done.stdout.strip())


def ping_completion(p: Project) -> Result:
    return _ping(p, "completion model", "bdc-assist",
                 'from r_assist.config import get_llm; print(get_llm().invoke("Reply with OK.").text[:80])',
                 "check COMPLETION_* and the API key in bdc-assist/.env")


def ping_embedding(p: Project) -> Result:
    return _ping(p, "embedding endpoint", "bdc-doc-mcp",
                 'from r_doc_mcp.config import get_emb; print(len(get_emb().embed_query("ping")))',
                 "check EMBEDDING_* (and the key, for openai/azure) in bdc-doc-mcp/.env and bdc-doc-builder/.env")


def ping_decision(p: Project) -> Result:
    """One tiny Decision-1 question (only when USE_DECISION_MODEL=true); prints its yes probability."""
    return _ping(p, "decision model", "bdc-assist",
                 "import asyncio; from r_assist.config import get_decider; "
                 'a = asyncio.run(get_decider()({"message": "Hello there"}, '
                 '{"q": {"type": "noul", "instructions": "Is `message` a greeting?"}})); print(a["q"]["noul"])',
                 "check DECISION_MODEL, DECISION_URL and the Azure key in bdc-assist/.env")


def start(cmd: list[str], cwd: Path, log: Path) -> subprocess.Popen:
    """Start cmd in its own process group (uv run starts a child python; stop() ends both)."""
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "w", encoding="utf-8") as out:
        if os.name == "nt":
            return subprocess.Popen(cmd, cwd=cwd, stdout=out, stderr=subprocess.STDOUT,
                                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        return subprocess.Popen(cmd, cwd=cwd, stdout=out, stderr=subprocess.STDOUT, start_new_session=True)


def stop(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        proc.wait()
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
    except ProcessLookupError:
        proc.wait()


def _get(url: str, timeout: float = 5):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, json.loads(r.read() or b"null")


def wait_http(url: str, timeout: float, proc: subprocess.Popen | None = None) -> bool:
    """True once url answers 200; False after timeout, or as soon as proc (if given) has exited."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return True
        except (OSError, ValueError):
            pass
        if time.monotonic() >= deadline or (proc is not None and proc.poll() is not None):
            return False
        time.sleep(0.5)


def _tail(log: Path, n: int = 20) -> str:
    return "\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]) if log.exists() else ""


def live_chat(p: Project, question: str, timeout: float = 120) -> list[Result]:
    """Bring up doc-mcp and the bot (reusing any already answering /health), ask one question, then stop
    what this run started."""
    mcp_port = _int(p.env["bdc-doc-mcp"].get("MCP_PORT"), DEFAULT_MCP_PORT)
    api_port = _int(p.env["bdc-assist"].get("API_PORT"), DEFAULT_API_PORT)
    services = [("bdc-doc-mcp", ["uv", "run", "python", "-m", "r_doc_mcp.mcp_server", "--http"], mcp_port),
                ("bdc-assist", ["uv", "run", "uvicorn", "r_assist.api:app", "--port", str(api_port)], api_port)]
    started, out = [], []
    try:
        for repo, cmd, port in services:
            health = f"http://127.0.0.1:{port}/health"
            if wait_http(health, 0):
                out.append(Result(f"{repo} service", "pass", f"already running on {port}, reused"))
                continue
            log = p.root / "data" / "logs" / f"{repo}.log"
            proc = start(cmd, p.root / repo, log)
            started.append(proc)
            if not wait_http(health, timeout, proc):
                return out + [Result(f"{repo} service", "fail", f"no answer on {health} after {timeout:g}s; "
                                     f"last lines of {log}:\n{_tail(log)}", "fix what the log says, then re-run")]
            out.append(Result(f"{repo} service", "pass", f"started on {port}"))
        _, health = _get(f"http://127.0.0.1:{api_port}/health")
        if (health or {}).get("mcp_errors"):
            return out + [Result("live chat", "fail", "the bot can't reach: " + "; ".join(health["mcp_errors"]),
                                 "check the MCP server urls in mcp_servers.yaml and that those servers are up")]
        request = urllib.request.Request(f"http://127.0.0.1:{api_port}/chat", method="POST",
                                         data=json.dumps({"input": question, "chat_history": []}).encode(),
                                         headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=max(timeout, 120)) as r:
            reply = json.loads(r.read())
        return out + [Result("live chat", "pass", f"Q: {question}\n{reply.get('answer', '')}\n{reply.get('sources_md', '')}")]
    except (OSError, ValueError) as e:
        return out + [Result("live chat", "fail", f"{type(e).__name__}: {e}", "see data/logs/ for the services' output")]
    finally:
        for proc in started:
            stop(proc)


def _live(p: Project, so_far: list[Result]) -> list[Result]:
    if any(r.status == "fail" for r in so_far):
        return [Result("live chat", "fail", "skipped", "fix the failures above first")]
    path = p.config["bdc-assist"] / "sample_questions.yaml"
    questions = _yaml(path) if path.is_file() else []
    if not isinstance(questions, list) or not questions:
        return [Result("live chat", "fail", f"no questions in {path}", "add a list of sample questions there")]
    return live_chat(p, str(questions[0]))


def report(results: list[Result]) -> None:
    for r in results:
        print(f"{r.status.upper()} {r.name}" + (f": {r.detail}" if r.detail else ""))
        if r.fix and r.status != "pass":
            print(f"  fix: {r.fix}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project", type=Path)
    parser.add_argument("--offline", action="store_true", help="static checks only: no model calls")
    parser.add_argument("--live", action="store_true", help="also start the services and ask one sample question")
    args = parser.parse_args(argv)
    p = load_project(args.project)
    results = check_files(p)
    if not any(r.status == "fail" for r in results):
        for c in (check_agreement, check_placeholders, check_custom_names, check_decision, check_sources,
                  check_ports, check_deploy_choice, check_server, check_k8s):
            results += c(p)
        if not args.offline:
            results += [ping_completion(p), ping_embedding(p)]
            if _decision_on(p.env["bdc-assist"]):
                results.append(ping_decision(p))
        if args.live:
            results += _live(p, results)
    report(results)
    return 1 if any(r.status == "fail" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
