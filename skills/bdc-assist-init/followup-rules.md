# Follow-up rules

How to ask the questions in `questions.yaml`, and when to ask more.

## Asking

- One question per message, in plain words. Rephrase `text` to suit the person, and keep its meaning.
- New to the stack (`you.familiarity`): give the question's `why` in one line, and offer its default.
  Skip `depth: experienced` questions and use their defaults, recorded as `default`.
- Experienced: no explanations. Also ask the `depth: experienced` questions, and offer the advanced
  settings when they come up: `chunk_size` and `chunk_overlap` (builder `build.yaml`), `node_timeout`,
  `keep_session`, reasoning effort, `MCP_RETRY_SECONDS`, `MAX_RUNNING_CHATS`, `MAX_WAITING_CHATS`.
- Suggest values that can be worked out instead of asking for them: the short name, the bot's name,
  the slug (`COLLECTION_NAME`, from the short name). The slug is lowercase letters, digits and `-`,
  at least 3 characters, starting and ending with a letter or digit. The search database refuses
  anything else, so pad a short one: `mp` becomes `mp-docs`. Record them as `suggested` once the
  person accepts.
- Skip a question when its `skip_if` holds, and record nothing for it.

## When to ask a follow-up

- Only when an answer leaves a config value unknown or unclear, or it conflicts with another answer.
- At most 2 follow-ups per question. After that, use the default and record it as `assumed`.
- "I don't know" also takes the default, recorded as `default`.
- Record each follow-up and its answer under the question in `answers.yaml`.

## Check facts instead of asking

Check what can be checked, and record the result as `verified`:

- A URL answers (an HTTP request).
- A local path exists.
- A git repo can be read: `git ls-remote <url>`.
- An MCP server is reachable, and which tools it lists. A short script with the bdc-assist clone's
  environment, using `langchain_mcp_adapters` the same way the bot does, can list them.

If a check fails, say what failed and ask once. Don't guess.

## Custom code

- When an answer needs code of the project's own (`tools.reshape`, `tools.steps`, or anything else
  that can't be said in yaml), write down *what* it should do in `.bdc-assist-config/custom.md`, in
  the person's words.
- Never ask *how* it should be built. That is bdc-assist-custom's job.
- Never suggest, read or mention the example code under a clone's `examples/` (such as `dug_kg` or
  `related_work`) unless the person names it.

## Secrets

- Ask for API keys when needed. Write them only to `<clone>/.env` and `deploy/*.env.server`.
- Never repeat a key back, never put it in `answers.yaml` (record `given`) or `SETUP.md`, and never
  show it in a diff. Mask it as `***`.

## Watch for these

- **The docker deployment with local sources outside the project folder.** The server's builder
  only sees the project folder. Say so, and offer to copy the source into `content/` inside the
  project folder, pointing `sources.yaml` at the copy.
- **Stdio MCP servers on a server deployment.** A server started by a command (`transport: stdio`)
  only runs in the docker setup if that command exists in the bot's image, and the generated image
  has only bdc-assist. Say so; an HTTP server is the usual answer. The same goes for Kubernetes.
- **Kubernetes needs addresses the cluster can reach.** A model or MCP server on this machine
  (`localhost`) can't be reached from a cluster. Ask for the address the cluster uses. The content is
  built on this machine through a port-forward, so the builder's embedding address must be reachable
  from here too, and must serve the same model doc-mcp uses. If the person doesn't know the cluster's
  details (namespace, registry, web address), take the defaults and say the drafts must be checked
  with whoever runs the cluster.
- **One OpenAI key in the builder.** The builder's `.env` has a single `OPENAI_API_KEY` for both its
  completion model and its embeddings. If both are OpenAI-hosted with different keys, ask which one
  the builder should use. Azure can use `AZURE_OPENAI_API_KEY` for one of them instead.
- **"Same key as the chat model."** If that's the answer to `models.embedding_key`, still write the
  key to every embedding target, using the key given for `models.completion_key` earlier in this
  conversation. The search server's `.env` needs it too. On a re-run where that key isn't in the
  conversation, ask for it again, since env files are never read back.
- **The same embedding model everywhere.** The builder and the search server must use exactly the
  same embedding provider, address and model. Ask once and write it to both.
