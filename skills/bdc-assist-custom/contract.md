# The contract for interceptors.py and nodes.py

How bdc-assist loads a project's own code. Read the sources below in the project's bdc-assist
clone: they are the truth for the version the project runs, and this page only says where to look
and what matters. **Never open `examples/`**, even though those docstrings say "see examples/bdc".

| What | Where in `<project>/bdc-assist` |
|---|---|
| interceptors: how they're loaded and scoped | `load_interceptors` and `_only_for` in `r_assist/agent.py` |
| how a server's connection is built | `load_mcp_servers` in `r_assist/agent.py` |
| nodes: loading, settings, startup errors | `load_nodes` in `r_assist/graph.py` |
| slots, timeouts, which fields a node may write | `build_graph`'s docstring and its `extra()` wrapper in `r_assist/graph.py` |
| the state a node reads and writes | `BotState` in `r_assist/graph.py` |
| attached knowledge graphs and sources | `_kgs` and `_attached_sources` in `r_assist/graph.py` |
| prompts a node reads | `PROMPTS` in `r_assist/prompts.py` |
| the yaml side | README, "Configure for your project" |

## Interceptors (`config/bdc-assist/interceptors.py`)

- A langchain-mcp-adapters tool interceptor: `async def name(request, handler)`. Call
  `result = await handler(request)`, change it, and return it. `request.name` is the tool, `request.args` its
  arguments, `request.server_name` the server.
- Register it per server in `mcp_servers.yaml`: `interceptors: [name, ...]`. It then runs on that
  server's tool calls only, the first listed outermost.
- The result is an `mcp.types.CallToolResult`. Leave it alone when `result.isError` is set or the
  content isn't what you expect. Return `result.model_copy(update=...)` rather than mutating it.
- `content` is what the agent's model reads. To give the client something the model never sees, put
  it in `structuredContent`:
  - `structuredContent["kg"]`: a knowledge graph, which bdc-assist lifts into the response's `kg` list.
    Its shape is whatever the web client draws; read `_kgs` and the bdc-assist README's API section.
  - `structuredContent["sources"] = {key: [{title, link, type}]}`: listed under the answer's sources.
- Startup fails if a name in `interceptors:` isn't a function in `interceptors.py`.

## Nodes (`config/bdc-assist/nodes.py`)

- A node is a factory: `def name(llm, tools, settings)` returns `async def node(state) -> dict`
  (a state update), or `None` for no step (for example, when the tool it needs isn't loaded, or is a
  stand-in: `tool.metadata.get("stand_in")`).
- Register it in `project.yaml`:

  ```yaml
  extra_nodes:
    before_agent:          # or after_agent / after_finish
      detect_language:     # the function's name in nodes.py
        label: Checking your language…   # what a web client shows while it runs
        fields: [user_lang]              # state fields of its own: later nodes read them, the API returns them
        min_words: 3                     # anything else is the node's own setting, handed to it
  node_timeout:            # optional, seconds per slot (30 each unless set)
    before_agent: 10
  ```

  The template `project.yaml` has `extra_nodes` only as a commented example. Add the real block
  after it, and leave the comments in place.
- Slots:
  - `before_agent`: runs in order, after the input checks and before the agent, for example to
    rewrite `question`. Returning `{"answer": ...}` ends the chat with that answer. The agent sees
    only `question` (and its system prompt), so changing `question` is how a node steers the agent.
    For example, append "Answer in French." to it.
  - `after_agent`: runs side by side with the answer check and the follow-ups. It may write only the
    fields it lists, none of `BotState`'s, and no two `after_agent` nodes may list the same field. A
    rejected answer drops them.
  - `after_finish`: runs in order on an answer that passed its check, before the disclaimers, for
    example to reshape `answer` or add to `sources`.
- A node that raises, or runs past its slot's timeout, is logged and skipped. The chat goes on. A key
  in its update that is neither a `BotState` field nor one it lists is dropped.
- It reads its prompt texts from `r_assist.prompts.PROMPTS["<key>"]`. Add the key to
  `config/bdc-assist/prompts.yaml`. `${...}` placeholders there must be `project.yaml` keys, and
  `{...}` slots are for the node's own `.format()`.
- Startup fails if a node named in `extra_nodes` isn't in `nodes.py`, or its settings aren't a
  mapping, or `fields` isn't a list of names, or two `after_agent` nodes list one field.

## The decision model in a node

When the project sets `USE_DECISION_MODEL=true` (bdc-assist's `.env`), Microsoft Decision-1 makes the
built-in yes/no and pick-one decisions. A node's own decisions can use it too. Read `get_decider` and
`DECISION_YES` in `r_assist/config.py`, and how `build_graph` calls it in `r_assist/graph.py`.

- In the factory: `decide = config.get_decider()` (`from r_assist import config`). It is `None` when
  the decision model is off.
- In the node: `answers = await decide(about, questions)`.
  - `about` is a dict of what is judged, for example `{"question": state["question"], "answer":
    state["answer"]}`.
  - `questions` is `{id: {"type": "noul", "instructions": "Is `answer` ...?"}}` for a yes/no. Its
    yes probability is `answers[id]["noul"]`, and a yes is `> config.DECISION_YES`.
  - For a pick-one it is `{id: {"type": "choice", "instructions": ..., "criteria": {name: None,
    ...}}}`, and the pick is `answers[id]["choice"]`.
  - Instructions name the keys of `about` in backticks.
- Write both paths. With `decide` set, ask Decision-1; otherwise ask `llm` as before. Writing text
  (search terms, a rewrite, a translation) stays with `llm` either way.
- Its decision instructions go in `prompts.yaml` under keys ending in `_decision`. In the factory,
  require them only when `decide` is set, raising `ValueError` naming the missing keys. That stops
  startup with a clear message, as the built-in checks do.
- Test both paths. For the decision path, monkeypatch `config.get_decider` to return an async fake
  that gives fixed probabilities, and check one answer above `DECISION_YES` and one below.

## Tests (`config/bdc-assist/tests/`)

Run them with the clone's environment, as a module so the clone is on the path:

```
uv run --directory "<project>/bdc-assist" python -m pytest "<project>/config/bdc-assist/tests" -q
```

Inside that run the clone's `.env` is loaded, so `CONFIG_DIR` already points at the project's
config. `from r_assist.graph import load_nodes` and `from r_assist.agent import load_interceptors`
then load the project's own files.

- **Load the file under test** with `importlib.util.spec_from_file_location`, from
  `Path(__file__).parent.parent / "nodes.py"` (or `interceptors.py`).
- **Node:** call the factory with a fake `llm` (an object with `async def ainvoke(messages)`
  returning `langchain_core.messages.AIMessage`), the `tools` it needs (or `[]`) and its settings.
  Then `asyncio.run(node(state))` and assert on the update. Cover the "no step" case too, and
  `load_nodes()` returning it.
- **Interceptor:** build the `CallToolResult` from a saved sample (`CallToolResult.model_validate(json)`),
  then pass `handler = lambda request: <async returning it>` and `request =
  types.SimpleNamespace(name=..., args=..., server_name=...)`. Assert on the returned result,
  including an error result coming back unchanged.

## A real tool response (for an interceptor)

Before writing an interceptor, save what the tool really returns. Run this from the clone, with the
server running:

```
uv run --directory "<project>/bdc-assist" python -c "import asyncio, json, sys; from langchain_mcp_adapters.client import MultiServerMCPClient; from r_assist.agent import load_mcp_servers
async def main(server, tool, args):
    client = MultiServerMCPClient({server: load_mcp_servers()[server]})
    async with client.session(server) as s:
        print((await s.call_tool(tool, json.loads(args))).model_dump_json(indent=1))
asyncio.run(main(*sys.argv[1:]))" <server> <tool> '{"query": "..."}'
```

Save its output as `config/bdc-assist/tests/samples/<server>-<tool>.json`, one per tool the
interceptor handles. If the server isn't reachable, say so and stop: an interceptor written
against a guessed shape breaks on the real one.
