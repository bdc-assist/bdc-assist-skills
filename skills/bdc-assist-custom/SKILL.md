---
name: bdc-assist-custom
description: Use when a BDC Assist project needs its own interceptors.py or nodes.py, such as reshaping an MCP server's tool results or adding a step before or after the bot answers
---

# bdc-assist-custom

Build the project-specific code of a BDC Assist bot: interceptors (reshape one MCP server's tool
results) and nodes (extra steps before or after the answer). The project was set up by
bdc-assist-init, and its needs are listed in `.bdc-assist-config/custom.md`.

## Hard rules

1. **The clone stays untouched.** Code goes in `<project>/config/bdc-assist/interceptors.py` /
   `nodes.py`, tests in `config/bdc-assist/tests/`. Never edit `<project>/bdc-assist`. If a need
   can't be met within the contract, say so instead of patching bdc-assist.
2. **No examples by default.** Learn the contract from `contract.md` and the clone's own code
   (`r_assist/agent.py`, `r_assist/graph.py`). Never read, copy or mention anything under
   `examples/`, unless the person names it (for example `related_work` or `dug_kg`). Then see
   **Copying a named example**.
3. **Real data first.** Before writing an interceptor, call the real tool and save its response
   (contract.md, "A real tool response"). Never write against a guessed shape.
4. **Tested before done.** Every function gets a test that runs and passes, and `check.py` passes,
   before it's marked built.

## Files

- `contract.md` (this skill's base directory): where the contract lives in the clone, its rules,
  how to test, and how to fetch a real tool response.
- bdc-assist-init's scripts, at `<this base dir>/../bdc-assist-init/scripts/`:
  - `check.py "<project>" --offline` checks that every name in the yaml exists in the code.
  - `state.py record "<project>" <files>` records what you wrote, so a re-run of init won't
    overwrite it.

## Flow

1. **What's wanted.** Read `.bdc-assist-config/custom.md` and `answers.yaml`. A need the person
   brings now is added to `custom.md` first, in their words, with `status: open`. Work on one need
   at a time.
2. **Learn the contract.** Read `contract.md`, then the clone sources it points to. They are the
   truth for this version.
3. **Pick the shape.** For each need, choose:
   - an interceptor, when it changes what one server's tools return
   - a node, when it's a step of the chat: `before_agent`, `after_agent` or `after_finish`

   Say why in one line, then confirm the behavior with the person: what goes in, what comes out,
   what happens when it fails, and which model calls it costs. A node that makes a yes/no or
   pick-one decision gets a decision-model path too (contract.md, "The decision model in a node").
   It's used when the project sets `USE_DECISION_MODEL=true`, and the chat model is used otherwise.
   Write the choice into `custom.md` (`kind`, `where`).
4. **Real data.** For an interceptor, fetch and save the real response of each tool it handles, in
   `config/bdc-assist/tests/samples/`.
5. **Write and register it.**
   - The function goes in `interceptors.py` / `nodes.py` (create the file if needed, with a
     docstring saying what each function does).
   - An interceptor is registered in `mcp_servers.yaml` (`interceptors: [name]` on its server). A
     node goes in `project.yaml`, under `extra_nodes.<slot>.<name>`, with `label`, `fields` and
     its own settings, plus `node_timeout` if 30 s doesn't fit.
   - Prompts it needs go in `prompts.yaml`, under a key named after the node.
6. **Test it.** Write `config/bdc-assist/tests/test_<name>.py` (contract.md, "Tests"), covering the
   normal case, the "nothing to do" case and a failure. Run:
   `uv run --directory "<project>/bdc-assist" python -m pytest "<project>/config/bdc-assist/tests" -q`
   Fix the code until every test passes.
7. **Check it.** Run `uv run "<init scripts>/check.py" "<project>" --offline` until nothing fails.
   Then offer the live check (`--live`, a few model calls) with a sample question that exercises
   the new code. Add one to `sample_questions.yaml` if none does.
8. **Record it.** Set the need's line in `custom.md` to
   `status: built <YYYY-MM-DD>: <function> in <file>`. Then
   `state.py record "<project>" config/bdc-assist/nodes.py config/bdc-assist/project.yaml ...`, for
   every file you wrote, including the tests, samples, `custom.md` and any yaml. Tell them what
   changed, what it costs per chat, and to restart the bot.

## Copying a named example

Only when the person names it (for example "add related_work like BDC has"):

1. Copy that one function from the clone's `examples/bdc/nodes.py` or `interceptors.py`, with the
   helpers and imports it uses, and nothing else from there.
2. Copy its registration from `examples/bdc/project.yaml` or `mcp_servers.yaml`, and its prompts
   from `examples/bdc/prompts.yaml`. Copy its decision-model prompts too (keys ending in
   `_decision`, e.g. `related_search_decision`), so turning the decision model on later just works.
   Rewrite BDC-specific wording for this project, using `${name}` / `${short_name}`.
3. Say what it depends on. For example, `related_work` needs a server with a
   `search_publications` tool (BDC uses artie-mcp), and `dug_kg` needs dug-mcp's result shape. If
   that's missing, the step does nothing until it's added.
4. Test it as in step 6, and check it as in step 7.
5. Record it in `custom.md`:

   ```markdown
   ## related-work
   - kind: node
   - what: <their words>
   - where: after_agent
   - status: copied from examples/bdc <YYYY-MM-DD>
   ```

   Then `state.py record` the files.

## Red flags

| Thought | Do this instead |
|---|---|
| "`examples/bdc/nodes.py` shows the pattern, I'll grep it" | `contract.md` and `r_assist/graph.py` have the contract. Open `examples/` only for a named example. |
| "A tiny change in `r_assist` would make this easy" | Never edit the clone. Work within the contract, or say it can't be done. |
| "I know what the tool returns" | Fetch and save the real response first. |
| "The test can sit next to `nodes.py`" | `config/bdc-assist/tests/test_<name>.py`. |
| "pytest can't import r_assist, set PYTHONPATH" | `uv run --directory "<clone>" python -m pytest ...` puts the clone on the path. |
| "`status: done`" | `status: built <date>: <function> in <file>`, or `copied from examples/bdc <date>`. |
| "This after_agent node should rewrite `answer`" | after_agent nodes can't write `BotState` fields. Use `after_finish`. |
| "Copy the whole BDC example config" | Only the named function, its helpers, registration and prompts. |
| "Tests pass, I'm done" | Also `check.py --offline`, `custom.md`, and `state.py record`. |
| "This yes/no step just asks the llm" | Write the decision-model path too, `config.get_decider()`, and test both. |
