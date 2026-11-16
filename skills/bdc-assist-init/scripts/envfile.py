# /// script
# requires-python = ">=3.12"
# dependencies = ["python-dotenv"]
# ///
"""Write the project's .env files by target name, so no command line names a .env path and no secret
is ever printed (secret-guard hooks block reading .env files; this never needs to).

  uv run envfile.py set   <project> <target> KEY=VALUE ... [--dry-run]
  uv run envfile.py token <project> [--server]

Targets: bdc-assist | bdc-doc-mcp | bdc-doc-builder   -> <project>/<repo>/.env (new from its .env.example)
         server:<repo>                              -> <project>/deploy/<repo>.env.server
         deploy                                     -> <project>/deploy/.env (new from the skill's template)
set: each KEY replaces its line (also a commented-out "# KEY=" one), keeping that line's trailing comment;
     new keys are appended. Prints "KEY: old -> new" per key, with *** for secrets.
token: one new INGEST_TOKEN into bdc-doc-mcp and bdc-doc-builder (their .env.server files with --server),
       unless both already hold the same real one (kept).
"""
import argparse
import re
import secrets
import sys
from pathlib import Path

from dotenv import dotenv_values

REPOS = ("bdc-assist", "bdc-doc-mcp", "bdc-doc-builder")
DEPLOY_TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "deploy" / "env"
SECRET = re.compile(r"KEY|TOKEN|SECRET|PASSWORD", re.I)


def target_paths(root: Path, target: str) -> tuple[Path, Path | None]:
    """(the file, the template a new one starts from)."""
    if target in REPOS:
        return root / target / ".env", root / target / ".env.example"
    if target.startswith("server:") and target[7:] in REPOS:
        return root / "deploy" / f"{target[7:]}.env.server", None
    if target == "deploy":
        return root / "deploy" / ".env", DEPLOY_TEMPLATE
    raise ValueError(f"unknown target {target!r}: use one of {', '.join(REPOS)}, server:<repo>, deploy")


def _quote(value: str) -> str:
    if re.search(r"[\s#\"'\\]", value):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


def _line(key: str, value: str, old_line: str | None, keep_comment: bool) -> str:
    line = f"{key}={_quote(value)}"
    comment = None
    if old_line is not None:
        body = old_line.lstrip().removeprefix("#").lstrip()
        m = re.search(r"\s#\s?(.*)$", body.split("=", 1)[1]) if "=" in body else None
        comment = m.group(1).strip() if m else None
    # never "KEY=   # note" (docker reads the note as the value), and no inline comments where docker reads it
    if comment and value and keep_comment:
        line += f"  # {comment}"
    return line


def _show(key: str, value: str | None) -> str:
    if value is None:
        return "(unset)"
    if value == "":
        return "(empty)"
    return "***" if SECRET.search(key) else value


def set_values(root: Path, target: str, kv: dict[str, str], dry_run: bool = False) -> list[str]:
    path, template = target_paths(Path(root), target)
    old = dict(dotenv_values(path)) if path.is_file() else {}
    source = path if path.is_file() else template if template and template.is_file() else None
    lines = source.read_text(encoding="utf-8").splitlines() if source else []
    keep_comment = target in REPOS  # python-dotenv reads "KEY=value  # note" as value; docker files get no notes
    for key, value in kv.items():
        pattern = re.compile(rf"^\s*(#\s*)?(export\s+)?{re.escape(key)}\s*=")
        hits = [i for i, l in enumerate(lines) if pattern.match(l)]
        active = [i for i in hits if not lines[i].lstrip().startswith("#")]
        i = (active or hits or [None])[0]
        if i is None:
            lines.append(_line(key, value, None, keep_comment))
        else:
            lines[i] = _line(key, value, lines[i], keep_comment)
    changes = [f"{k}: {_show(k, old.get(k))} -> {_show(k, v)}" for k, v in kv.items()]
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return changes


def token(root: Path, server: bool = False) -> str:
    targets = [f"server:{r}" if server else r for r in ("bdc-doc-mcp", "bdc-doc-builder")]
    held = []
    for t in targets:
        path, _ = target_paths(Path(root), t)
        held.append(dotenv_values(path).get("INGEST_TOKEN") if path.is_file() else None)
    names = ", ".join(targets)
    if held[0] and held[0] == held[1] and held[0] != "change-me":
        return f"INGEST_TOKEN kept in {names}"
    value = secrets.token_urlsafe(32)
    for t in targets:
        set_values(root, t, {"INGEST_TOKEN": value})
    return f"INGEST_TOKEN set in {names} (new)"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    st = sub.add_parser("set", help="set keys in one target's env file")
    st.add_argument("root", type=Path)
    st.add_argument("target")
    st.add_argument("pairs", nargs="+", metavar="KEY=VALUE")
    st.add_argument("--dry-run", action="store_true", help="print the changes, write nothing")
    tk = sub.add_parser("token", help="one shared INGEST_TOKEN for doc-mcp and the builder")
    tk.add_argument("root", type=Path)
    tk.add_argument("--server", action="store_true", help="the deploy/*.env.server pair instead of the clones' .env")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "token":
            print(token(args.root, args.server))
            return 0
        bad = [p for p in args.pairs if "=" not in p]
        if bad:
            raise ValueError(f"not KEY=VALUE: {', '.join(bad)}")
        kv = dict(p.split("=", 1) for p in args.pairs)
        for change in set_values(args.root, args.target, kv, args.dry_run):
            print(change)
        for key in [k for k, v in kv.items() if "$" in v]:  # names only: the value may be a secret
            print(f"warning: {key}: the value holds a '$'. python-dotenv expands ${{...}} (even in quotes) and "
                  "docker expands $NAME, so it may not read back as written. Run check.py to confirm.",
                  file=sys.stderr)
    except ValueError as e:
        print(f"envfile: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
