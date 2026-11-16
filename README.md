# bdc-assist-skills

A Claude Code plugin that sets up a [BDC Assist](https://github.com/bdc-assist/bdc-assist) chatbot
for your own project. It covers three repos:

- the bot, [bdc-assist](https://github.com/bdc-assist/bdc-assist)
- its documentation search server, [bdc-doc-mcp](https://github.com/bdc-assist/bdc-doc-mcp)
- the content builder, [bdc-doc-builder](https://github.com/bdc-assist/bdc-doc-builder)

Claude asks about your project, writes every config file, explains how to run it, and checks that it
works. Your answers are saved, so you can change the setup later without starting over.

## Install

In Claude Code:

```
/plugin marketplace add bdc-assist/bdc-assist-skills
/plugin install bdc-assist-skills@bdc-assist
```

You need [git](https://git-scm.com) and [uv](https://docs.astral.sh/uv/). uv brings Python 3.12. You
also need a completion model and an embedding model, both reached over an API, local or remote:
OpenAI, Azure, vLLM or Ollama.

## The skills

| Skill | Run it directly | Or just ask |
|---|---|---|
| bdc-assist-init | `/bdc-assist-skills:bdc-assist-init` | "Set up a BDC Assist bot for my project" |
| bdc-assist-custom | `/bdc-assist-skills:bdc-assist-custom` | "Show our dataset search results as a graph in the web client" |

Claude also picks the right skill on its own when a request fits one.

**bdc-assist-init** sets up a project, changes an existing one, or checks one. In an empty folder,
ask for example:

- "Set up a BDC Assist bot for my project"
- "Change my bot's model to gpt-4.1" (in a folder it set up)
- "Check my bdc-assist setup"

It asks about the project, what the bot must refuse, where the docs live, fixed answers, other
MCP servers, the models, and local or server. You can also pick a decision model, Microsoft
Decision-1, to make the bot's yes/no checks. Then it:

1. clones the three repos
2. writes their config
3. writes `SETUP.md`
4. runs the checks
5. offers to build the search database
6. with a server, drafts a docker setup (`docker-compose.yml`, `Dockerfile`, `*.env.server`). This
   is a starting point to review: it is checked for consistency, but never built or run by us.

Anything that needs code of your own is written down, not built.

**bdc-assist-custom** builds that code. Init offers it at the end, and you can ask for it any time.
There are two kinds:

- **`interceptors.py`** changes what one of your MCP servers returns before the bot sees it. For
  example: "Our dataset search server returns plain rows; turn them into a graph the web client
  can draw."
- **`nodes.py`** adds a step before or after the bot answers. For example: "Before answering,
  expand our internal acronyms in the question, so the search finds the right documents."

It tests what it writes. It never touches BDC's own example code unless you name it, as in "add
related_work like BDC has".

## What you get

```
my-project/
  .bdc-assist-config/   answers.yaml (the questions and your answers), custom.md (custom code needs),
                        repos.yaml (cloned commits), written.yaml (to spot hand edits)
  config/               the project's settings: bdc-assist/, bdc-doc-mcp/, bdc-doc-builder/
  bdc-assist/  bdc-doc-mcp/  bdc-doc-builder/      the clones; only their .env files are yours
  data/                 the built content, the search database, logs
  deploy/               docker-compose.yml, Dockerfile, *.env.server (only with a server)
  SETUP.md              how to start, build, chat, check, deploy and change it
```

Keys and tokens live only in the `.env` files. They never go into the saved answers or `SETUP.md`.

## Scripts you can run yourself

The skills use three scripts, and each also works on its own. Run them with
[uv](https://docs.astral.sh/uv/), which installs what they need. `<scripts>` is the plugin's
`skills/bdc-assist-init/scripts` folder. After `/plugin install` it's under
`~/.claude/plugins/cache/bdc-assist/bdc-assist-skills/<version>/`. `<project>` is your project
folder. Quote both: project paths often hold spaces, `&` or `!`.

**check.py** checks a setup:
- the settings each repo needs, and that they agree across the repos and the server files
- the yaml files, the prompts and the custom code names

```
uv run "<scripts>/check.py" "<project>"            # settings, plus one tiny call per model
uv run "<scripts>/check.py" "<project>" --offline  # settings only, no model calls
uv run "<scripts>/check.py" "<project>" --live     # also start everything and ask the first sample question
```

**envfile.py** changes a `.env` value without opening the file. It never prints a key:

```
uv run "<scripts>/envfile.py" set "<project>" bdc-assist COMPLETION_MODEL=gpt-4.1 --dry-run  # show old -> new, write nothing
uv run "<scripts>/envfile.py" set "<project>" bdc-assist OPENAI_API_KEY=sk-...               # keys show as ***
uv run "<scripts>/envfile.py" token "<project>"            # a shared ingest token for bdc-doc-mcp and bdc-doc-builder
uv run "<scripts>/envfile.py" token "<project>" --server   # the server's own token, in deploy/*.env.server
```

The targets are:
- `bdc-assist`, `bdc-doc-mcp` and `bdc-doc-builder`: the clones' `.env`
- `server:<repo>`: `deploy/<repo>.env.server`
- `deploy`: `deploy/.env`

**state.py** shows which files changed since the skill last wrote them:

```
uv run "<scripts>/state.py" status "<project>"   # edited / missing files, and clone templates that changed
```

## Not covered yet

- **The web client** ([bdc-assist-client](https://github.com/bdc-assist/bdc-assist-client)). Its
  branding is still built into its code. Point it at your bot with `VITE_API_URL`.

## Contributing

```
uv run pytest
```

The tests cover the scripts (`check.py`, `state.py`, `envfile.py`), the question set and the
templates. `tests/rehearsal/` holds a scripted user for a full end-to-end run of the init skill.
That run uses fake embeddings and no model calls.
