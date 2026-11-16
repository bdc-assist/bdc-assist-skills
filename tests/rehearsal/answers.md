# Rehearsal: the scripted user

What the user answers, per question id in `skills/bdc-assist-init/questions.yaml`. A rehearsal
agent follows the init skill and takes these answers instead of asking. Free to run: the embeddings
are fake and nothing calls the completion model (the key is not real).

| id | answer |
|---|---|
| you.familiarity | new to it |
| project.name | Lumen Research Platform |
| project.short_name | Lumen |
| project.assistant_name | (accept the suggestion) |
| project.purpose | helps researchers use the platform: getting access, workspaces, uploading data |
| project.audience | researchers, many of them new to the platform |
| project.followups | 0 |
| rules.refuse | nothing extra |
| rules.house | short answers, always cite the documentation |
| content.sources | the markdown files in `<skills repo>/tests/rehearsal/docs` (a local folder) |
| content.doc_types | one kind: docs |
| content.dated | no |
| fixed.wanted | no |
| fixed.topics | (skipped) |
| tools.servers | none |
| tools.reshape | (skipped) |
| tools.steps | no |
| models.completion | openai, gpt-4o-mini |
| models.completion_key | sk-rehearsal |
| models.reasoning_effort | (not asked: new user) |
| models.embedding | provider fake, model fake, URL http://localhost:11434 (tests only) |
| models.embedding_key | (skipped: no key needed) |
| models.contextualize | no |
| running.where | both: this machine and a server |
| running.ports | (not asked: defaults) |
| running.cors | https://lumen.example.org |
| running.chat_limits | (not asked: defaults) |
| samples.questions | accept the proposed list |
| build the content now? | yes |
| live check? | no (the key is not real) |
| copy the docs into the project folder? | no |

Expected afterwards:

- The project folder layout from the spec.
- `answers.yaml` holds every id that was asked or defaulted. Skipped ones (`skip_if`) are left out.
- `state.py status` is clean.
- `check.py --offline` exits 0. Its warnings are fake embeddings, and the docs source lying outside
  the project folder (there is a server deployment).
- `sk-rehearsal` appears only in `bdc-assist/.env`, `bdc-doc-builder/.env`, and their two
  `deploy/*.env.server` twins, never in `answers.yaml` or `SETUP.md`.
- After the build, `POST http://127.0.0.1:8001/search` with `{"query": "lumen upload", "mode": "keyword"}`
  finds the rehearsal docs (doc-mcp's `--http` process serves it beside `/mcp`), and the bot's
  `/health` reports no `mcp_errors`.
