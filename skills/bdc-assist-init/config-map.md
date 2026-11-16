# Config map

Which answer goes where, and how. A target `repo/<file>#<key>` in `questions.yaml` means
`config/<repo>/<file>`, except `repo/.env`, which is the clone's own `.env`. `deploy/...` is the
project's `deploy/` folder.

## How each file is made

Start every file from the clone's current copy, never from memory or a copy in this skill:

| Project file | Starts from (in the clone) | Then |
|---|---|---|
| `config/bdc-assist/project.yaml` | `config/project.yaml` | set the keys below |
| `config/bdc-assist/prompts.yaml` | `config/prompts.yaml` | edit the prompts below; keep every other key as is |
| `config/bdc-assist/predefined_responses.yaml` | `config/predefined_responses.yaml` | add the topics, or keep only its comments |
| `config/bdc-assist/mcp_servers.yaml` | `config/mcp_servers.yaml` | edit `r_doc_mcp`, add other servers |
| `config/bdc-assist/sample_questions.yaml` | (new) | a yaml list of questions |
| `config/bdc-doc-mcp/doc_types.yaml` | `config/doc_types.yaml` | set `project` and `types` |
| `config/bdc-doc-mcp/prompts.yaml` | `config/prompts.yaml` | copy unchanged |
| `config/bdc-doc-builder/sources.yaml` | `config/sources.yaml` | keep its header comment, replace the commented examples with the real entries |
| `config/bdc-doc-builder/prompts.yaml` | `config/prompts.yaml` | copy unchanged |
| `config/bdc-doc-builder/build.yaml` | `config/build.yaml` | copy unchanged, unless an experienced user sets `chunk_size` / `chunk_overlap` |
| `<repo>/.env` | `<repo>/.env.example` | `envfile.py set "<project>" <repo> KEY=VALUE ...` (it starts from the example and uncomments `# KEY=` lines) |

YAML edits keep the template's comments. Quote any string value that contains `: ` or ` #`, or starts
with a special character (`description: "Docs: access, uploads"`). Otherwise the file doesn't parse
and the service won't start. `check.py` parses every yaml the services read.

In `prompts.yaml` and the `mcp_servers.yaml` prompts, keep every `{input}`, `{answer}`, `{topics}`,
`{date}`, `{tools}` slot exactly as written. Use only `${name}`, `${short_name}`, `${assistant_name}`,
`${followups}` (or another key of `project.yaml`) as `${...}` placeholders. Anything else fails
bdc-assist's startup.

bdc-assist runs some prompts through `.format()`: `agent_system`, `input_guardrail_human`,
`output_guardrail_human`, `suggest_followups_human`, `topic_classifier_system` and the `sources*`
lines. In those, a brace in the person's own words must be written twice (`{{` and `}}`). A single
one breaks the bot, at startup or on every chat. `check.py` flags any `{...}` there that isn't one of
the slots.

After writing files, record them with `state.py record "<project>" --env ...`. `--env` takes every
env file, each clone `.env` with its `.env.example`. Name every other file with its clone template
(`config/bdc-assist/project.yaml=bdc-assist/config/project.yaml`, ...). Files with no template
(sample questions, deploy files, `SETUP.md`, `.gitignore`) are named without one.

### Env file rules

- Write env files only with `envfile.py`. The targets are `bdc-assist`, `bdc-doc-mcp`,
  `bdc-doc-builder` (the clones' `.env`), `server:<repo>` (`deploy/<repo>.env.server`) and
  `deploy` (`deploy/.env`). Never read them and never name their paths in a shell command.
  `envfile.py set ... --dry-run` shows old -> new with secrets as `***`.
- It writes `KEY=value`, quoting values with spaces or `#`. It never leaves `KEY=   # note`, which
  docker reads as the value `# note`.
- Forward slashes in paths, also on Windows.
- Secrets only in these files.

## By target

### bdc-assist (the bot)

- `bdc-assist/project.yaml#name`, `bdc-assist/project.yaml#short_name`,
  `bdc-assist/project.yaml#assistant_name`: the answers, as written.
- `bdc-assist/project.yaml#followups`: the number; `0` removes the follow-up step entirely.
  Leave `append_disclaimer`, `doc_search_tool` and `sources_key` as they are.
- `bdc-assist/prompts.yaml#agent_system`: keep the template's sentences and slots. After the first
  sentence about the assistant, add one or two sentences on what the bot is for (`project.purpose`)
  and who asks (`project.audience`). Replace or extend the answer-style sentences with the house
  rules (`rules.house`). Keep the `{tools}` slot on the line that introduces the tools.
- `bdc-assist/prompts.yaml#input_guardrail_human`: make the "Must be related to" line say what the
  bot is for (`project.purpose`). Add each `rules.refuse` item as one more `- No ...` line in the
  policy list. Keep `{input}`.
- `bdc-assist/prompts.yaml#decision_input_guardrail`: the same edits as questions, for Decision-1: make
  the "Is `message` unrelated to" line say what the bot is for, and add each `rules.refuse` item as one
  more ``- Does `message` ...?`` line, phrased so that yes means refuse.
  Keep this list in step with `input_guardrail_human` even while the decision model is off, so turning
  it on later needs no prompt work. Keep the template's `decision_output_guardrail` and
  `decision_classify` as they are; their `${...}` placeholders fill in like the others.
- `bdc-assist/predefined_responses.yaml`: `fixed.wanted = no` → keep only the template's comments
  (an empty file: no canned answers or disclaimers; a bdc-assist with the no-topics shortcut also
  skips the topic match's model call, while an older one still makes it, matching nothing). Otherwise one
  entry per topic:
  ```yaml
  Short topic name:
    response: "The text. ${short_name} placeholders work here."
    flag: "r"        # r = replaces the answer (no search), a = added after the answer
    title: "Shown under the answer's sources"
    link: ""         # may be empty
  ```
  Never name a topic `other`: with the decision model on, that is its "none of them" pick, and
  bdc-assist refuses to start.
- `bdc-assist/mcp_servers.yaml`: keep the `r_doc_mcp` key (the demo scripts look for it), and set
  its `url` to `http://127.0.0.1:<MCP_PORT>/mcp`. Keep `stand_ins: [search_docs]` and
  `keep_session: true`. For each other server in `tools.servers`, add a block with
  `transport` (`streamable_http`, `sse` or `stdio`), `url` (or `command` + `args` for stdio), a
  `prompt: |` saying when and how to use its tools, `stand_ins` (the tools the prompt names), and
  `keep_session: true` only if the server is stateless. Name the block after the service in
  snake_case, ending in `_mcp` (e.g. `osa_search_mcp`). Its URL override variable is the name
  uppercased plus `_URL` (`OSA_SEARCH_MCP_URL`). If the server isn't reachable, so its tools are
  unknown, write a prompt from what the person said, leave `stand_ins` out, and add a WARN line
  to the final summary. A re-run can fill them in once it's up.
- `bdc-assist/mcp_servers.yaml#r_doc_mcp.prompt`: `content.dated = no` → drop the paragraph about
  dates (from "Search results are ranked by relevance, NOT date" to "leave date_to unset."). Keep
  the rest.
- `bdc-assist/sample_questions.yaml`: a yaml list of 5–8 strings, each with a trailing comment
  saying what it tests: a regular question, an exact name or acronym (keyword search), one per
  fixed answer, one dated question if `content.dated`. The check asks the first one, so make the
  first a plain regular question.
- `bdc-assist/.env#COMPLETION_MODEL_PROVIDER`, `bdc-assist/.env#COMPLETION_MODEL`,
  `bdc-assist/.env#COMPLETION_URL`: the provider (`openai`, `azure`, `vllm`, `ollama`, always written
  explicitly), the model (for Azure, the deployment name), and the URL for azure / vllm / ollama
  (Azure: the resource root). For an OpenAI-compatible gateway with provider `openai`, set
  `OPENAI_BASE_URL` instead of `COMPLETION_URL`.
- `bdc-assist/.env#OPENAI_API_KEY`: the key (openai, vllm with a key). For Azure, write it as
  `AZURE_OPENAI_API_KEY` instead. Ollama needs none.
- `bdc-assist/.env#COMPLETION_REASONING_EFFORT`: unset for non-reasoning models (they reject it);
  `none` / `low` / `medium` / `high` otherwise.
- `bdc-assist/.env#USE_DECISION_MODEL`: `true` when `models.decision` is yes, else leave it unset.
  With it on, Decision-1 answers the input check (one yes/no per line of
  `decision_input_guardrail`; any yes blocks), the topic match (one pick among the topics and
  `other`), and the answer check (`decision_output_guardrail`; a no rejects). A config node can use it
  too. The chat model still rewrites follow-ups, writes the answers and suggests follow-up questions.
  Turn it on only with a bdc-assist whose `.env.example` lists `USE_DECISION_MODEL`.
- `bdc-assist/.env#DECISION_MODEL`: the Azure deployment name; leave it unset for the default
  `Decision-1`.
- `bdc-assist/.env#DECISION_URL`: the Azure resource, `https://<name>.services.ai.azure.com`. It can
  be left unset when the completion model is on that same resource: bdc-assist then takes the host of
  `COMPLETION_URL` or `OPENAI_BASE_URL`.
- `bdc-assist/.env#AZURE_OPENAI_API_KEY`: the decision model's key (bdc-assist reads it first, then
  `OPENAI_API_KEY`). An Azure completion model reads the same variable, so with both on Azure they
  share one key: use one resource for both.
- `bdc-assist/.env#API_PORT`: default `8010`.
- `bdc-assist/.env#CORS_ORIGINS`: comma-separated origins; locally `*` is fine.
- `bdc-assist/.env#MAX_RUNNING_CHATS`, `bdc-assist/.env#MAX_WAITING_CHATS`: experienced users only;
  locally unset (no cap).
- Always: `CONFIG_DIR=../config/bdc-assist`.

### bdc-doc-mcp (the search server)

- `bdc-doc-mcp/doc_types.yaml#project`: the project's full name.
- `bdc-doc-mcp/doc_types.yaml#types`: one entry per kind, `{description, default}`. The
  description is shown to the bot, so say what the kind contains. `default: true` means it's
  searched when the bot names no type. Default: one type `docs`, `default: true`.
- `bdc-doc-mcp/.env#COLLECTION_NAME`: the slug, from the short name. It needs at least 3 characters,
  starting and ending with a letter or digit (`mp` becomes `mp-docs`), and the same value goes in
  `deploy/bdc-doc-mcp.env.server`.
- `bdc-doc-mcp/.env#EMBEDDING_MODEL_PROVIDER`, `bdc-doc-mcp/.env#EMBEDDING_URL`,
  `bdc-doc-mcp/.env#EMBEDDING_MODEL`: always all three, written explicitly (the provider guess from
  the URL picks vllm for an Ollama URL without "ollama" in it), the same as the builder's.
- `bdc-doc-mcp/.env#OPENAI_API_KEY`: the embedding key, for openai (or `AZURE_OPENAI_API_KEY` for
  azure). None for ollama.
- `bdc-doc-mcp/.env#MCP_PORT`: default `8001`. This one process serves the bot (`/mcp`) and the
  builder (`/ingest/*`). Port 8000 (the standalone API) is not used.
- Always: `CONFIG_DIR=../config/bdc-doc-mcp`, `DB_PATH=../data/chroma`, and `INGEST_TOKEN` (below).

### bdc-doc-builder (the content builder)

- `bdc-doc-builder/sources.yaml`: one entry per source: `source_type` (`path`, `url`, `git`,
  `youtube`, `freshdesk`, `transcripts`, `yaml`), `doc_type` (a type from `doc_types.yaml`), `link`,
  and optional `exclude`. Relative links resolve against `config/bdc-doc-builder/`. A source inside
  the project folder gets a relative link (e.g. `../../content/guides`); one outside it gets an
  absolute path with forward slashes.
- `bdc-doc-builder/.env#COMPLETION_MODEL_PROVIDER`, `bdc-doc-builder/.env#COMPLETION_MODEL`,
  `bdc-doc-builder/.env#COMPLETION_URL`: the same model as the bot (it writes the chunk summaries
  when contextualizing). A gateway: `OPENAI_BASE_URL`, as for the bot.
- `bdc-doc-builder/.env#OPENAI_API_KEY`: shared by its completion model and its embeddings (see
  followup-rules.md, "One OpenAI key in the builder").
- `bdc-doc-builder/.env#COMPLETION_REASONING_EFFORT`: as for the bot.
- `bdc-doc-builder/.env#EMBEDDING_MODEL_PROVIDER`, `bdc-doc-builder/.env#EMBEDDING_URL`,
  `bdc-doc-builder/.env#EMBEDDING_MODEL`: exactly the same as doc-mcp's.
- Always: `CONFIG_DIR=../config/bdc-doc-builder`, `PREPROC_DATA_DIR=../data/build/`,
  `REPOS_DIR=../data/repos/`, `DOC_MCP_URL=http://127.0.0.1:<MCP_PORT>`, and `INGEST_TOKEN` (below).
- `models.contextualize = no` → the build command gets `--no-contextualize`:
  `uv run python -m r_doc_builder.ingest --build --reset --no-contextualize`.

### The ingest token

`envfile.py token "<project>"` writes one new token as `INGEST_TOKEN` into `bdc-doc-mcp/.env` and
`bdc-doc-builder/.env`. `envfile.py token "<project>" --server` writes the server's own, different
one into `deploy/bdc-doc-mcp.env.server` and `deploy/bdc-doc-builder.env.server`. Both keep a token
that is already set and matching, so re-runs never change it. The value is never printed.

## Custom code needs

- `.bdc-assist-config/custom.md`: `tools.reshape` and `tools.steps` answers (and anything else that
  needs code of the project's own) become one section each, in the format in SKILL.md. Nothing is
  written to `interceptors.py`, `nodes.py`, `extra_nodes:` or `interceptors:` by init;
  bdc-assist-custom does that.

## The server deployment (`running.where` includes a server)

- `deploy/docker-compose.yml`, `deploy/Dockerfile`, `deploy/Dockerfile.dockerignore`: copy the
  skill's `templates/deploy/` files unchanged. Compose sets the container plumbing itself
  (`CONFIG_DIR`, `MCP_HOST`, `MCP_PORT`, `DB_PATH`, `R_DOC_MCP_URL`, `DOC_MCP_URL`,
  `PREPROC_DATA_DIR`, `REPOS_DIR`); don't put those in the `.env.server` files.
- `deploy/.env#API_PORT`: the bot's published port (default `8010`).
- `deploy/.env#BUILD_FLAGS`: `--no-contextualize` when `models.contextualize = no`, else empty
  (`BUILD_FLAGS=` with nothing after it).
- `deploy/bdc-assist.env.server`: the bot's model settings and key
  (`deploy/bdc-assist.env.server#OPENAI_API_KEY`), `deploy/bdc-assist.env.server#CORS_ORIGINS`
  (required, the real site origins, never `*`),
  `deploy/bdc-assist.env.server#MAX_RUNNING_CHATS` and
  `deploy/bdc-assist.env.server#MAX_WAITING_CHATS` (default 10 and 30), and a `<NAME>_URL` for
  each other MCP server (the server key uppercased, e.g. `DUG_MCP_URL`) that points somewhere else
  than in `mcp_servers.yaml`. With the decision model, the same four as locally:
  `deploy/bdc-assist.env.server#USE_DECISION_MODEL`, `deploy/bdc-assist.env.server#DECISION_MODEL`,
  `deploy/bdc-assist.env.server#DECISION_URL` and `deploy/bdc-assist.env.server#AZURE_OPENAI_API_KEY`.
  Decision-1 is always remote, so no `host.docker.internal` rewrite applies.
- `deploy/bdc-doc-mcp.env.server`: `COLLECTION_NAME`, the server `INGEST_TOKEN`, the three
  `EMBEDDING_*`, the embedding key (`deploy/bdc-doc-mcp.env.server#OPENAI_API_KEY`), and
  `ANONYMIZED_TELEMETRY=False`.
- `deploy/bdc-doc-builder.env.server`: the server `INGEST_TOKEN`, the three `EMBEDDING_*`,
  `COMPLETION_*`, and its key (`deploy/bdc-doc-builder.env.server#OPENAI_API_KEY`).
- Inside a container, `localhost` and `127.0.0.1` mean the container itself. Write any model URL or
  other MCP server URL that points at this machine as `host.docker.internal` (compose maps it to the
  host).

## What must agree (check.py enforces these)

- `INGEST_TOKEN`: set, the same in `bdc-doc-mcp/.env` and `bdc-doc-builder/.env`, not `change-me`.
- `EMBEDDING_MODEL_PROVIDER`, `EMBEDDING_URL`, `EMBEDDING_MODEL`: set and the same in both.
- The builder's `DOC_MCP_URL` port = doc-mcp's `MCP_PORT`.
- The bot's `r_doc_mcp` url (or `R_DOC_MCP_URL` in `bdc-assist/.env`) = `http://...:<MCP_PORT>/mcp`.
- Every `${...}` in the bot's yaml is a key of `project.yaml`.
- Every function named under `interceptors:` or `extra_nodes:` exists in `interceptors.py` /
  `nodes.py`.
- Every local source exists.
- No `.env` line is an empty value followed by a comment.
- With `USE_DECISION_MODEL=true` (locally or in `deploy/bdc-assist.env.server`), these must hold:
  - `prompts.yaml` has `decision_input_guardrail` (a `- ` list) and `decision_output_guardrail`.
  - It also has `decision_classify` when there are topics.
  - No topic is named `other`.
  - There is a `DECISION_URL`, or a `COMPLETION_URL` / `OPENAI_BASE_URL` to take its host from.

  The check pings Decision-1 too.
