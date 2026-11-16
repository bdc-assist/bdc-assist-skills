---
name: bdc-assist-init
description: Use when setting up a BDC Assist chatbot (bdc-assist, bdc-doc-mcp, bdc-doc-builder) for a project, changing the answers or files of an existing setup, or checking that a setup works
---

# bdc-assist-init

Set up a BDC Assist bot for someone's project by talking it through: ask about the project, clone the
three repos, write their config into the project folder, write `SETUP.md`, and check it all works.
Everything asked and answered is saved, so the setup can be re-run and changed later.

The repos: `https://github.com/bdc-assist/bdc-assist.git` (the bot), `.../bdc-doc-mcp.git` (the
documentation search server), `.../bdc-doc-builder.git` (builds the search database), all on `main`.

## Hard rules

1. **The clones stay untouched.** Inside a clone, write only its `.env`. Every config file goes in
   the project's own `config/<repo>/`, and each `.env` points `CONFIG_DIR` at it. Never edit a
   clone's `config/`, `examples/` or code.
2. **No examples by default.** Never read, copy, suggest or mention anything under a clone's
   `examples/` folder (for instance `dug_kg`, `related_work`), even when a need sounds like one,
   unless the person names it. Docstrings that say "see examples/bdc" are not an invitation.
3. **Secrets live in `.env` files only.** API keys go to `<clone>/.env` and `deploy/*.env.server`.
   `answers.yaml` records `given`; `SETUP.md`, diffs and your replies show `***`. Never repeat a key.
   Never read an env file, and never name one in a shell command (secret-guard hooks block that).
   Write them only with `envfile.py`, which takes a target name and prints secrets as `***`.
   `check.py` reads them for you.
4. **No silent overwrites.** Before writing a file that exists, run `state.py status`. If the file
   was edited by hand, ask: keep it, overwrite it, or show both. Show a diff before every write
   during a re-run.
5. **One doc-mcp process.** `python -m r_doc_mcp.mcp_server --http` on `MCP_PORT` (8001) serves
   both the bot (`/mcp`) and the builder (`/ingest`). Don't use the standalone API on port 8000.
6. **Custom code is recorded, not built.** Needs for `interceptors.py` / `nodes.py` go into
   `.bdc-assist-config/custom.md`. Building them is bdc-assist-custom's job, after a yes.

## Files

In this skill's base directory (the path shown when the skill loads):

| File | What it is |
|---|---|
| `questions.yaml` | the fixed questions, their ids, defaults and targets |
| `followup-rules.md` | how to ask, when to follow up, what to check instead of asking |
| `config-map.md` | which answer goes into which file and key, fixed values, server values |
| `templates/` | `SETUP.md` outline, `gitignore`, `deploy/` docker files |
| `scripts/envfile.py` | `set` keys in an env file by target name; `token` for the shared `INGEST_TOKEN` |
| `scripts/state.py` | `record` / `status`: hashes of written files, for hand-edit detection |
| `scripts/check.py` | static checks, model endpoint pings, `--live` chat |

Run the scripts with uv (they bring their own dependencies):
`uv run "<base dir>/scripts/check.py" "<project>"`. Quote every path: project folders often hold
spaces, `&` or `!`.

The project folder, when done:

```
<project>/
  .bdc-assist-config/  answers.yaml  custom.md  repos.yaml  written.yaml
  config/bdc-assist/  config/bdc-doc-mcp/  config/bdc-doc-builder/
  bdc-assist/  bdc-doc-mcp/  bdc-doc-builder/     clones (only .env written)
  data/                                           built content, database, logs
  deploy/                                         only for a server deployment
  SETUP.md  .gitignore
```

## Flow

### 1. Where are we?

Work in the folder the person names, or the current one if it is empty or already a project. If
`.bdc-assist-config/answers.yaml` exists, this is a re-run: go to **Re-run** below. If the folder
holds unrelated files, ask before using it.

### 2. Prerequisites

Check `git --version` and `uv --version`. If one is missing, say how to install it
(https://git-scm.com, https://docs.astral.sh/uv/getting-started/installation/) and stop. Python
3.12 isn't needed up front: uv installs it.

### 3. Clone

For each repo: `git clone <url> "<project>/<repo>"`. If the folder already exists, reuse it: don't
re-clone, and warn if `git -C "<clone>" status --porcelain` shows local changes. Then
`uv --directory "<clone>" sync` in each (slow the first time; say so). Write
`.bdc-assist-config/repos.yaml`:

```yaml
bdc-assist: {url: https://github.com/bdc-assist/bdc-assist.git, branch: main, commit: <git -C <clone> rev-parse HEAD>}
```

and the same for the other two.

### 4. Ask

Go through `questions.yaml` in order, following `followup-rules.md`. One question per message.
After each section, save `.bdc-assist-config/answers.yaml`, so an interrupted session can pick up
at the first unanswered id:

```yaml
questions_version: 1
updated: <YYYY-MM-DD>
answers:
  - id: project.name
    asked: "<the question as you asked it>"
    answer: "<their answer, or the value used>"
    source: user        # user | suggested | default | assumed | verified
    followups:          # only if there were any
      - {q: "...", a: "..."}
  - id: models.completion_key
    answer: given       # secrets: never the value
    source: user
```

Needs for custom code (`tools.reshape`, `tools.steps`, or anything else yaml can't express) go
into `.bdc-assist-config/custom.md`, one section each, in the person's words:

```markdown
## <short-name>
- kind: interceptor | node | undecided
- what: <what it should do, in their words>
- where: <MCP server name, or before_agent | after_agent | after_finish, or undecided>
- status: open
```

`samples.questions` comes last: propose 5–8 test questions from the answers (see config-map.md)
and let them edit the list.

### 5. Write the config

Show a short summary of what will be written: files, and the key choices; no secrets. Then write
each config file as `config-map.md` says, starting from the clone's current template.

Write the env files with `envfile.py`, one call per target. A new file starts from the clone's
`.env.example`, so its comments stay:

```
uv run "<base dir>/scripts/envfile.py" set "<project>" bdc-doc-mcp CONFIG_DIR=../config/bdc-doc-mcp MCP_PORT=8001 ...
uv run "<base dir>/scripts/envfile.py" token "<project>"
```

The second line writes one shared `INGEST_TOKEN` into doc-mcp and the builder, and keeps it if
it's already there. Then record everything you wrote:

```
uv run "<base dir>/scripts/state.py" record "<project>" --env config/bdc-assist/project.yaml=bdc-assist/config/project.yaml ...
```

`--env` records every env file of the project. Name every other written file, each with its
clone template when it came from one. Also copy `templates/gitignore` to `<project>/.gitignore` and
record it.

### 6. SETUP.md

Copy `templates/SETUP.md` and replace each `<!-- init: ... -->` comment with the real text for this
project and this person's OS: PowerShell and `demo_services.ps1` on Windows, bash and
`demo_services.sh` elsewhere. Fill in the real ports, paths and sample question. No secrets. Record
it.

### 7. Check

Run `uv run "<base dir>/scripts/check.py" "<project>"`. It makes two tiny model calls, one per
endpoint. Fix every FAIL it reports (re-ask the question behind it if needed) and run it again until
nothing fails. Explain any WARN in one line.

### 8. Build the content (offer it)

Ask before building, with the time: about a minute without contextualizing, up to about 30 minutes
for a large site with it (`models.contextualize`). On yes:

1. Start doc-mcp in the background: `uv run python -m r_doc_mcp.mcp_server --http`, run in
   `<project>/bdc-doc-mcp`.
2. Wait for `http://127.0.0.1:<MCP_PORT>/health`.
3. Run in `<project>/bdc-doc-builder`: `uv run python -m r_doc_builder.ingest --build --reset`
   (plus `--no-contextualize` if they said no).
4. Confirm `/health` now shows `documents` above 0, then stop doc-mcp. On failure, show the error
   (doc-mcp's own output first: a config that doesn't parse stops it at startup) and the builder's
   README section on retrying.

After a build, offer the live check (`check.py "<project>" --live`): it starts the services, asks the
first sample question, prints the answer and its sources, and stops what it started. It costs a few
model calls; ask first.

### 9. Server deployment (only if `running.where` includes a server)

Create `deploy/`:
- Copy `templates/deploy/docker-compose.yml`, `Dockerfile` and `Dockerfile.dockerignore` unchanged.
- `envfile.py set "<project>" deploy API_PORT=... BUILD_FLAGS=...` writes `deploy/.env`, starting from
  the template.
- `envfile.py set "<project>" server:<repo> ...` writes each of the three `.env.server` files as
  config-map.md says. Use `host.docker.internal` for this machine's URLs, and a real
  `CORS_ORIGINS`. Then `envfile.py token "<project>" --server` writes the server's own
  `INGEST_TOKEN`.

Record them all (`state.py record "<project>" --env deploy/docker-compose.yml ...`). Re-run
`check.py` (it also checks the `.env.server` files).

### 9b. Kubernetes (only if `running.where` includes Kubernetes)

Draft `deploy/k8s/` from `templates/deploy/k8s/`, as config-map.md's Kubernetes section says. Fill
every `${...}`: namespace, registry, tag and disk size. Write `ingress.yaml` only when there's a web
address. Copy `templates/deploy/Dockerfile` and `Dockerfile.dockerignore` too, since the images are
built from them.

The three `.env.server` files are written as in step 9, with two differences:
- The bot's and doc-mcp's model URLs must be ones the cluster can reach.
- The builder file is for building on this machine through a port-forward, so it gets
  `DOC_MCP_URL=http://127.0.0.1:18001`.

Say plainly that these files are a draft to review with whoever runs the cluster, and that nothing
was applied. Record them, and re-run `check.py`. It checks that every fill-in is filled, that the
files parse, that doc-mcp stays at one copy, and it warns on model URLs the cluster can't reach.

### 10. Custom code

If `custom.md` has open needs, list them and ask: "Do you want to build the custom parts now?" On
yes, use the bdc-assist-custom skill. On no, `SETUP.md` already says how to start it later.

End with a short summary covering what was set up, what's left, and where `SETUP.md` is.

## Re-run

When `answers.yaml` exists:

1. Run `state.py status "<project>"`.
   - `edited`: files changed by hand since the last write. Each will be asked about before writing.
   - `missing`: files deleted since the last write.
   - `template_changed`: the clone's template changed (after a `git pull`). Show that template's
     diff; apply it to the project file only if they say so.
2. Show the saved answers, section by section, and ask what they want to change. Any id in
   `questions.yaml` missing from `answers.yaml` (a newer `version`) is asked too, unless its
   `skip_if` holds. Skipped questions are never recorded, so don't re-ask them.
3. Regenerate only the files the changed answers touch. For each one, show the diff, write it after
   a yes, and `record` it. For env files, `envfile.py set ... --dry-run` shows the changes with
   secrets masked, and the same call without `--dry-run` writes them. For an `edited` file: keep,
   overwrite, or show both. Never overwrite it without an answer.
   An `edited` file the change doesn't touch needs no question. Leave it, and mention it in the
   summary.
4. Never re-clone. Offer `git -C "<clone>" pull` for each clone, and update `repos.yaml` with the new
   commits.
5. Update `answers.yaml` (the new answer, `source`, `updated`) and any part of `SETUP.md` the change
   makes stale, and record both. Keep the existing `INGEST_TOKEN`s. Run the check again, and say
   which services need a restart.

## Check on its own

When someone asks to check their setup: `uv run "<base dir>/scripts/check.py" "<project>"`
(`--offline` for no model calls, `--live` to also chat). Explain each FAIL and its fix, and offer to
make the fix through a re-run.

## Red flags

| Thought | Do this instead |
|---|---|
| "I'll just edit the clone's `config/` files, the README says to" | The project's `config/<repo>/` plus `CONFIG_DIR` in `.env`. Clones get only `.env`. |
| "BDC already has a knowledge-graph interceptor; let me look at `examples/bdc`" | Don't open `examples/`. Write the need into `custom.md`. |
| "A quick interceptor sketch would help them" | No code in init. Record the need; bdc-assist-custom builds it after a yes. |
| "I'll note the key in the answers so the next session has it" | `answer: given`. The key lives only in `.env` files. |
| "Let me confirm the key back to them" | Never echo it. Say "the key is saved in the .env files". |
| "No canned answers, so I'll delete `predefined_responses.yaml`" | Keep the file with only its comments. bdc-assist needs it to exist. |
| "Regenerating all files is simplest on a re-run" | `state.py status` first. Regenerate only what changed, diff each, ask about hand edits. |
| "Start the doc API on 8000 for the build, as the README does" | One `mcp_server --http` process on `MCP_PORT`. |
| "The docs site is one `url` source" | A `url` source reads one page. Ask for the docs' git repo or local copy, or list the pages. |
| "Generate a fresh ingest token on the re-run" | Keep it. `envfile.py token` keeps an existing one. |
| "Let me read the `.env` to see what's in it" | Don't. `envfile.py set --dry-run` shows old -> new, masked; `check.py` validates. |
| "I'll write the `.env` with the Write tool, it's quicker" | `envfile.py set`: it keeps the template's comments and never writes `KEY=   # note`. |
