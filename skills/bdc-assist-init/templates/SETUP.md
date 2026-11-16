# <Project name>: BDC Assist setup

<!-- init: one line: what this bot is for, and the date of this setup. Write every command for the
     user's shell (bash/zsh, or PowerShell on Windows), with every path in quotes: project folders
     often hold spaces, & or !. Never write a secret anywhere in this file. -->

## Prerequisites

<!-- init: git, uv (https://docs.astral.sh/uv/), Python 3.12 (uv installs it if missing), and the two
     model endpoints this project uses (completion and embedding), saying which must be running
     before the services start (e.g. `ollama serve` for a local Ollama). -->

## What was set up

<!-- init: a short summary from answers.yaml, no secrets: the project names, what the bot is for,
     the content sources and doc types, fixed answers (or "none"), follow-up suggestions (or "off"),
     other MCP servers, the models (provider + model name only), whether the decision model
     (Decision-1) makes the yes/no checks, the ports, local or server. -->



## Start the services

<!-- init: from the bdc-assist clone, the demo script starts the search server (port <MCP_PORT>) and
     the bot (port <API_PORT>), and Ctrl-C stops them:
       cd "<project>/bdc-assist" && ./demo_services.sh
     PowerShell (two lines: Windows PowerShell 5.1 has no &&; the default execution policy blocks
     scripts, hence the Bypass):
       cd "<project>/bdc-assist"
       powershell -ExecutionPolicy Bypass -File .\demo_services.ps1
     It reuses a service already listening on those ports; say to stop any stray one first. -->

## Build the content

<!-- init: start the search server first (its one process takes the content and serves the bot):
       cd "<project>/bdc-doc-mcp" && uv run python -m r_doc_mcp.mcp_server --http
     then, in another terminal:
       cd "<project>/bdc-doc-builder" && uv run python -m r_doc_builder.ingest --build --reset [--no-contextualize]
     with the time estimate. Re-run the build after the sources change; the search server serves the
     new content at once. -->

## Chat with the bot

<!-- init: open "<project>/bdc-assist/tests/ui/demo.html" in a browser (it calls
     http://localhost:<API_PORT>; add ?api=http://host:port for another address), or:
       curl -X POST http://localhost:<API_PORT>/chat -H "Content-Type: application/json" -d '{"input": "<first sample question>", "chat_history": []}'
     (PowerShell: Invoke-RestMethod with the same JSON). Point to config/bdc-assist/sample_questions.yaml. -->

## Check the setup

<!-- init: first: ask Claude "check my bdc-assist setup". Then the command, with check.py's real path
     written out (this skill's base directory + /scripts/check.py), noting the path changes when the
     plugin updates:
       uv run "<path>/check.py" "<project>"            settings + model endpoints
       ... --offline   no model calls;   ... --live   also start the services and ask one question -->



## Deploy to a server

<!-- init: only with a server deployment; otherwise write "Not set up. Re-run bdc-assist-init to add one."
     1. Get the project folder onto the server, with the clones: copy the whole folder, or commit it
        to git (the clones are ignored) and on the server clone it, then for each repo in
        .bdc-assist-config/repos.yaml: git clone <url> "<repo>" && git -C "<repo>" checkout <commit>
     2. Copy the three deploy/*.env.server files over separately (they hold secrets and are not committed).
     3. cd deploy && docker compose up -d --build
     4. docker compose --profile build run --rm builder
     5. The bot answers on port <API_PORT>; the search server is not exposed. Put the bot behind HTTPS,
        and make sure CORS_ORIGINS lists the site that calls it. -->

## Change the setup

<!-- init: ask Claude to run bdc-assist-init again in this folder: it loads the saved answers, asks
     only what you want to change, and shows each file's changes before writing. Files you edited by
     hand are detected, and you choose whether to keep them. -->

## Custom code

<!-- init: the needs listed in .bdc-assist-config/custom.md, each with its status (open, or built and
     where). If any are open: "Ask Claude to build them with bdc-assist-custom." If none: "None." -->

## Where things are

<!-- init:
     config/                  the project's settings for the three repos (edit, then re-run the check)
     .bdc-assist-config/      answers.yaml (questions and answers), custom.md, repos.yaml, written.yaml
     bdc-assist/ bdc-doc-mcp/ bdc-doc-builder/   the clones (only their .env files are project-specific)
     data/                    built content, the search database, cloned git sources, service logs
     deploy/                  the docker setup (if any) -->
