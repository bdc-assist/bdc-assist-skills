import shutil
import socket

import yaml

import check
from conftest import set_env, write, write_yaml


def run_static(root):
    p = check.load_project(root)
    return [r for c in (check.check_files, check.check_agreement, check.check_placeholders,
                        check.check_custom_names, check.check_decision, check.check_sources, check.check_ports,
                        check.check_server)
            for r in c(p)]


def server_files(root, **override):
    """A server deployment: deploy/docker-compose.yml and three valid .env.server files; override = {file stem: text}."""
    embed = "EMBEDDING_MODEL_PROVIDER=ollama\nEMBEDDING_URL=http://host.docker.internal:11434\nEMBEDDING_MODEL=bge-m3\n"
    files = {"bdc-assist": "COMPLETION_MODEL=gpt-4o-mini\nCORS_ORIGINS=https://bot.example.org\n",
             "bdc-doc-mcp": "COLLECTION_NAME=demo\nINGEST_TOKEN=server-tok\n" + embed,
             "bdc-doc-builder": "INGEST_TOKEN=server-tok\n" + embed}
    write(root / "deploy/docker-compose.yml", "services: {}\n")
    for stem, text_ in (files | override).items():
        if text_ is not None:
            write(root / f"deploy/{stem}.env.server", text_)


def fails(results):
    return [r for r in results if r.status == "fail"]


def warns(results):
    return [r for r in results if r.status == "warn"]


def text(results):
    return " | ".join(f"{r.name}: {r.detail}" for r in results)


def edit_yaml(path, change):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(data)
    write_yaml(path, data)


def test_valid_project_passes(project, capsys):
    assert check.main([str(project), "--offline"]) == 0
    assert "FAIL" not in capsys.readouterr().out
    assert not warns(run_static(project))


def test_missing_config_file_fails(project):
    (project / "config/bdc-doc-mcp/doc_types.yaml").unlink()
    bad = fails(check.check_files(check.load_project(project)))
    assert bad and "doc_types.yaml" in text(bad)


def test_missing_config_file_skips_other_checks(project, capsys):
    (project / "config/bdc-doc-mcp/doc_types.yaml").unlink()
    set_env(project, "bdc-doc-builder", INGEST_TOKEN="other")
    assert check.main([str(project), "--offline"]) == 1
    assert "token" not in capsys.readouterr().out.lower()


def test_config_yaml_that_does_not_parse_fails(project, capsys):
    # an unquoted ": " in a value: doc-mcp crashed on exactly this in the rehearsal
    write(project / "config/bdc-doc-mcp/doc_types.yaml",
          "project: Demo\ntypes:\n  docs:\n    description: Demo documentation: access, workspaces\n")
    bad = fails(check.check_files(check.load_project(project)))
    assert bad and "doc_types.yaml" in text(bad) and "line 4" in text(bad)
    assert check.main([str(project), "--offline"]) == 1


def test_key_written_twice_fails(project):
    # bdc-assist's own loader refuses a key given twice (the second would silently replace the first)
    write(project / "config/bdc-assist/project.yaml", "name: Demo\nshort_name: D\nassistant_name: D Assist\n"
          "extra_nodes:\n  before_agent:\n    gone: {}\nextra_nodes:\n  after_finish: {}\n")
    bad = fails(check.check_files(check.load_project(project)))
    assert "written twice" in text(bad) and "project.yaml" in text(bad)


def test_collection_name_chroma_rejects_fails(project):
    for name in ("mp", "-demo", "demo-"):
        set_env(project, "bdc-doc-mcp", COLLECTION_NAME=name)
        assert "COLLECTION_NAME" in text(fails(run_static(project))), name


def test_collection_name_unset_passes(project):
    set_env(project, "bdc-doc-mcp", COLLECTION_NAME="")  # doc-mcp then uses its CONFIG_DIR folder's name
    assert not fails(run_static(project))


def test_server_env_valid_passes(project):
    server_files(project)
    results = run_static(project)
    assert not fails(results) and "server" in text([r for r in results if r.status == "pass"])


def test_server_env_file_missing_fails(project):
    server_files(project, **{"bdc-doc-builder": None})
    assert "bdc-doc-builder.env.server" in text(fails(run_static(project)))


def test_server_token_mismatch_fails(project):
    server_files(project, **{"bdc-doc-builder": "INGEST_TOKEN=other\nEMBEDDING_MODEL_PROVIDER=ollama\n"
                                                "EMBEDDING_URL=http://host.docker.internal:11434\nEMBEDDING_MODEL=bge-m3\n"})
    assert "server ingest token" in text(fails(run_static(project))).lower()


def test_server_embedding_mismatch_fails(project):
    server_files(project, **{"bdc-doc-builder": "INGEST_TOKEN=server-tok\nEMBEDDING_MODEL_PROVIDER=ollama\n"
                                                "EMBEDDING_URL=http://host.docker.internal:11434\nEMBEDDING_MODEL=nomic\n"})
    assert "server embedding" in text(fails(run_static(project))).lower()


def test_server_cors_must_be_real_origins(project):
    for cors in ("", "*", "https://a.example.org,*"):
        server_files(project, **{"bdc-assist": f"CORS_ORIGINS={cors}\n"})
        assert "CORS_ORIGINS" in text(fails(run_static(project))), cors


def test_server_collection_name_checked(project):
    server_files(project, **{"bdc-doc-mcp": "COLLECTION_NAME=ab\nINGEST_TOKEN=server-tok\nEMBEDDING_MODEL_PROVIDER=ollama\n"
                                            "EMBEDDING_URL=http://host.docker.internal:11434\nEMBEDDING_MODEL=bge-m3\n"})
    assert "COLLECTION_NAME" in text(fails(run_static(project)))


DECISION_PROMPTS = ('decision_input_guardrail: |\n  - Is `message` unrelated to ${name}?\n  - Does `message` ask for harm?\n'
                    'decision_output_guardrail: Is `answer` a helpful reply to `question`?\n'
                    'decision_classify: Which of these topics is `question` about?\n')


def decision_on(root, prompts=DECISION_PROMPTS, **env):
    set_env(root, "bdc-assist", USE_DECISION_MODEL="true", **({"DECISION_URL": "https://x.services.ai.azure.com"} | env))
    write(root / "config/bdc-assist/prompts.yaml", 'agent_system: "You are ${assistant_name}."\n' + prompts)


def test_decision_model_on_with_its_questions_passes(project):
    decision_on(project)
    assert not fails(run_static(project))


def test_decision_model_on_needs_its_questions(project):
    decision_on(project, prompts="")
    bad = text(fails(run_static(project)))
    assert "decision_input_guardrail" in bad and "decision_output_guardrail" in bad


def test_decision_classify_needed_only_with_topics(project):
    decision_on(project, prompts=DECISION_PROMPTS.split("decision_classify")[0])
    assert not fails(run_static(project))  # no topics: bdc-assist doesn't ask for it
    write(project / "config/bdc-assist/predefined_responses.yaml", "Billing:\n  response: See the billing page.\n  flag: r\n")
    assert "decision_classify" in text(fails(run_static(project)))


def test_decision_topic_named_other_fails(project):
    decision_on(project)
    write(project / "config/bdc-assist/predefined_responses.yaml", "Other:\n  response: x\n  flag: a\n")
    assert '"other"' in text(fails(run_static(project)))


def test_decision_input_rules_must_be_a_list(project):
    decision_on(project, prompts=DECISION_PROMPTS.replace("  - Is", "  Is").replace("  - Does", "  Does"))
    assert "decision_input_guardrail" in text(fails(run_static(project)))


def test_decision_model_needs_a_url(project):
    decision_on(project, DECISION_URL="")
    assert "DECISION_URL" in text(fails(run_static(project)))
    set_env(project, "bdc-assist", OPENAI_BASE_URL="https://x.openai.azure.com/openai/v1")  # its host is the fallback
    assert not fails(run_static(project))


def test_decision_model_off_ignores_missing_questions(project):
    set_env(project, "bdc-assist", USE_DECISION_MODEL="false")
    assert not fails(run_static(project))


def test_server_decision_model_needs_a_url(project):
    decision_on(project)
    server_files(project, **{"bdc-assist": "CORS_ORIGINS=https://bot.example.org\nUSE_DECISION_MODEL=true\n"})
    assert "DECISION_URL" in text(fails(run_static(project)))


def test_embedding_url_not_needed_for_openai(project):
    for repo in ("bdc-doc-mcp", "bdc-doc-builder"):  # OpenAI's own endpoint: the URL is never read
        set_env(project, repo, EMBEDDING_MODEL_PROVIDER="openai", EMBEDDING_URL="", EMBEDDING_MODEL="text-embedding-3-small")
    assert not fails(run_static(project))


def test_embedding_url_needed_for_ollama(project):
    for repo in ("bdc-doc-mcp", "bdc-doc-builder"):
        set_env(project, repo, EMBEDDING_URL="")
    assert "EMBEDDING_URL" in text(fails(run_static(project)))


def test_literal_brace_in_a_formatted_prompt_fails(project):
    # bdc-assist .format()s agent_system: a lone {name} that isn't one of its slots fails startup
    write(project / "config/bdc-assist/prompts.yaml", 'agent_system: "Today is {date}. Write code as {snippet}."\n')
    assert "{snippet}" in text(fails(run_static(project)))


def test_unbalanced_brace_in_a_formatted_prompt_fails(project):
    write(project / "config/bdc-assist/prompts.yaml", 'input_guardrail_human: "Check {input} }"\n')
    assert "input_guardrail_human" in text(fails(run_static(project)))


def test_doubled_braces_and_placeholders_pass(project):
    write(project / "config/bdc-assist/prompts.yaml",
          'agent_system: "You are ${assistant_name}. Today is {date}. Use {{curly}} braces. {tools}"\n'
          'related_filter_decision: "Does `papers[{n}]` fit?"\n')  # a node's own prompt: its own slots
    assert not fails(run_static(project))


def test_wrong_shape_yaml_fails_without_crashing(project, capsys):
    write(project / "config/bdc-assist/mcp_servers.yaml", "- r_doc_mcp\n")
    assert check.main([str(project), "--offline"]) == 1
    assert "mcp_servers.yaml" in capsys.readouterr().out


def test_wrong_shape_entries_fail_without_crashing(project, capsys):
    write(project / "config/bdc-assist/mcp_servers.yaml", "r_doc_mcp: http://127.0.0.1:8001/mcp\n")
    write_yaml(project / "config/bdc-doc-builder/sources.yaml", ["./docs", {"source_type": "path", "link": "./docs"}])
    edit_yaml(project / "config/bdc-assist/project.yaml", lambda d: d.update(extra_nodes=["lang"]))
    assert check.main([str(project), "--offline"]) == 1
    out = capsys.readouterr().out
    assert "r_doc_mcp" in out and "extra_nodes" in out


def test_yaml_no_service_reads_is_ignored(project):
    write(project / "config/bdc-doc-builder/docs/notes.yaml", "---\na: 1\n---\nb: !custom 2\n")  # content, not config
    assert not fails(run_static(project))


def test_included_sources_yaml_that_does_not_parse_fails(project):
    builder = project / "config/bdc-doc-builder"
    write_yaml(builder / "sources.yaml", [{"source_type": "yaml", "link": "more.yaml"}])
    write(builder / "more.yaml", "- source_type: path\n  link: a: b\n")
    assert "more.yaml" in text(fails(run_static(project)))


def test_sample_questions_that_do_not_parse_fail(project):
    write(project / "config/bdc-assist/sample_questions.yaml", "- What: is: this\n")
    assert "sample_questions.yaml" in text(fails(check.check_files(check.load_project(project))))


def test_config_dir_unset_fails(project):
    set_env(project, "bdc-assist", CONFIG_DIR="")
    assert fails(check.check_files(check.load_project(project)))


def test_missing_clone_fails_without_crashing(project):
    shutil.rmtree(project / "bdc-doc-builder")
    bad = fails(check.check_files(check.load_project(project)))
    assert bad and "bdc-doc-builder" in text(bad)


def test_token_mismatch_fails(project):
    set_env(project, "bdc-doc-builder", INGEST_TOKEN="other")
    assert "ingest token" in text(fails(run_static(project))).lower()


def test_example_token_fails(project):
    for repo in ("bdc-doc-mcp", "bdc-doc-builder"):
        set_env(project, repo, INGEST_TOKEN="change-me")
    assert "ingest token" in text(fails(run_static(project))).lower()


def test_env_value_that_is_a_comment_fails(project):
    for repo in ("bdc-doc-mcp", "bdc-doc-builder"):
        set_env(project, repo, INGEST_TOKEN="   # note")
    assert "comment" in text(fails(run_static(project))).lower()


def test_server_env_comment_value_fails(project):
    write(project / "deploy/bdc-doc-mcp.env.server", "INGEST_TOKEN=   # note\n")
    bad = fails(run_static(project))
    assert "comment" in text(bad).lower() and "bdc-doc-mcp.env.server" in text(bad)


def test_embedding_mismatch_fails(project):
    set_env(project, "bdc-doc-builder", EMBEDDING_MODEL="nomic")
    assert "embedding" in text(fails(run_static(project))).lower()


def test_embedding_provider_unset_fails(project):
    for repo in ("bdc-doc-mcp", "bdc-doc-builder"):
        set_env(project, repo, EMBEDDING_MODEL_PROVIDER="")
    assert "embedding" in text(fails(run_static(project))).lower()


def test_fake_embeddings_warn(project):
    for repo in ("bdc-doc-mcp", "bdc-doc-builder"):
        set_env(project, repo, EMBEDDING_MODEL_PROVIDER="fake")
    results = run_static(project)
    assert not fails(results) and "fake" in text(warns(results))


def test_builder_url_port_mismatch_fails(project):
    set_env(project, "bdc-doc-builder", DOC_MCP_URL="http://127.0.0.1:8000")
    assert "DOC_MCP_URL" in text(fails(run_static(project)))


def test_builder_url_unset_fails(project):
    set_env(project, "bdc-doc-builder", DOC_MCP_URL="")  # the builder's own default is :8000
    assert "DOC_MCP_URL" in text(fails(run_static(project)))


def test_bot_url_port_mismatch_fails(project, ports):
    edit_yaml(project / "config/bdc-assist/mcp_servers.yaml",
              lambda d: d["r_doc_mcp"].update(url=f"http://127.0.0.1:{ports[1] + 1}/mcp"))
    assert "r_doc_mcp" in text(fails(run_static(project)))


def test_bot_url_wrong_path_fails(project, ports):
    edit_yaml(project / "config/bdc-assist/mcp_servers.yaml",
              lambda d: d["r_doc_mcp"].update(url=f"http://127.0.0.1:{ports[1]}/sse"))
    assert "r_doc_mcp" in text(fails(run_static(project)))


def test_bot_url_env_override_wins(project, ports):
    edit_yaml(project / "config/bdc-assist/mcp_servers.yaml",
              lambda d: d["r_doc_mcp"].update(url="http://127.0.0.1:1/mcp"))
    set_env(project, "bdc-assist", R_DOC_MCP_URL=f"http://127.0.0.1:{ports[1]}/mcp")
    assert not fails(run_static(project))


def test_unknown_placeholder_fails(project):
    write(project / "config/bdc-assist/prompts.yaml", 'agent_system: "You are ${nme}."\n')
    assert "${nme}" in text(fails(run_static(project)))


def test_unknown_placeholder_in_mcp_prompt_fails(project):
    edit_yaml(project / "config/bdc-assist/mcp_servers.yaml", lambda d: d["r_doc_mcp"].update(prompt="Search ${projct} docs."))
    assert "${projct}" in text(fails(run_static(project)))


def test_escaped_dollar_is_not_a_placeholder(project):
    write(project / "config/bdc-assist/prompts.yaml", 'refusal: "Costs $${price} for ${name}."  # refusal is not .format()ed\n')
    assert not fails(run_static(project))


def test_placeholder_in_comment_ignored(project):
    assert not fails(check.check_placeholders(check.load_project(project)))


def test_missing_interceptor_fails(project):
    edit_yaml(project / "config/bdc-assist/mcp_servers.yaml", lambda d: d["r_doc_mcp"].update(interceptors=["shape"]))
    assert "interceptors.py" in text(fails(run_static(project)))


def test_missing_node_fails(project):
    edit_yaml(project / "config/bdc-assist/project.yaml", lambda d: d.update(extra_nodes={"before_agent": {"lang": {}}}))
    write(project / "config/bdc-assist/nodes.py", "def other(llm, tools, settings):\n    return None\n")
    bad = fails(run_static(project))
    assert "lang" in text(bad) and "nodes.py" in text(bad)


def test_custom_names_present_pass(project):
    edit_yaml(project / "config/bdc-assist/mcp_servers.yaml", lambda d: d["r_doc_mcp"].update(interceptors=["shape"]))
    write(project / "config/bdc-assist/interceptors.py", "async def shape(request, handler):\n    return await handler(request)\n")
    edit_yaml(project / "config/bdc-assist/project.yaml", lambda d: d.update(extra_nodes={"after_finish": {"tidy": {}}}))
    write(project / "config/bdc-assist/nodes.py", "from functools import partial\n\ndef _make(llm, tools, settings):\n"
                                                  "    return None\n\ntidy = partial(_make)\n")
    assert not fails(run_static(project))


def test_custom_code_syntax_error_fails(project):
    edit_yaml(project / "config/bdc-assist/mcp_servers.yaml", lambda d: d["r_doc_mcp"].update(interceptors=["shape"]))
    write(project / "config/bdc-assist/interceptors.py", "async def shape(request, handler)\n")
    assert "interceptors.py" in text(fails(run_static(project)))


def test_missing_local_source_fails(project):
    shutil.rmtree(project / "config/bdc-doc-builder/docs")
    assert "./docs" in text(fails(run_static(project)))


def test_missing_source_in_included_yaml_fails(project):
    builder = project / "config/bdc-doc-builder"
    write_yaml(builder / "sources.yaml", [{"source_type": "yaml", "link": "more/extra.yaml"},
                                          {"source_type": "url", "link": "https://example.org/x"}])
    write_yaml(builder / "more/extra.yaml", [{"source_type": "path", "doc_type": "docs", "link": "./gone"}])
    assert "./gone" in text(fails(run_static(project)))


def test_local_source_outside_project_warns_with_deploy(project, tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    write_yaml(project / "config/bdc-doc-builder/sources.yaml", [{"source_type": "path", "doc_type": "docs", "link": str(outside)}])
    assert not warns(run_static(project))  # no server deploy, no warning
    (project / "deploy").mkdir()
    results = run_static(project)
    assert not fails(results) and "project folder" in text(warns(results))


def test_port_in_use_warns(project, ports):
    with socket.socket() as s:
        s.bind(("127.0.0.1", ports[1]))
        s.listen()
        results = run_static(project)
    assert not fails(results) and str(ports[1]) in text(warns(results))
