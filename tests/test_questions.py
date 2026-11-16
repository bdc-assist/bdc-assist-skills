from pathlib import Path

import yaml

SKILL = Path(__file__).resolve().parent.parent / "skills/bdc-assist-init"
CONFIG_MAP = SKILL / "config-map.md"
DOC = yaml.safe_load((SKILL / "questions.yaml").read_text(encoding="utf-8")) if (SKILL / "questions.yaml").exists() else {}
QS = DOC.get("questions") or []
QS_BY_ID = {q["id"]: q for q in QS}
EXPECTED_IDS = [
    "you.familiarity",
    "project.name", "project.short_name", "project.assistant_name", "project.purpose", "project.audience",
    "project.followups",
    "rules.refuse", "rules.house",
    "content.sources", "content.doc_types", "content.dated",
    "fixed.wanted", "fixed.topics",
    "tools.servers", "tools.reshape", "tools.steps",
    "models.completion", "models.completion_key", "models.reasoning_effort", "models.embedding",
    "models.embedding_key", "models.contextualize", "models.decision", "models.decision_key",
    "running.where", "running.k8s_namespace", "running.k8s_registry", "running.k8s_host", "running.k8s_storage",
    "running.ports", "running.cors", "running.chat_limits",
    "samples.questions",
]


def test_version():
    assert DOC["version"] == 1


def test_ids_unique_and_complete():
    assert [q["id"] for q in QS] == EXPECTED_IDS


def test_required_fields():
    for q in QS:
        assert {"id", "section", "text", "why", "depth", "default", "secret", "fills"} <= q.keys(), q["id"]
        assert q["section"] == q["id"].split(".")[0], q["id"]


def test_depth_values():
    assert {q["depth"] for q in QS} <= {"everyone", "experienced"}
    assert [q["id"] for q in QS if q["depth"] == "experienced"] == [
        "models.reasoning_effort", "running.k8s_storage", "running.ports", "running.chat_limits"]


def test_secrets_only_fill_env_files():
    assert [q["id"] for q in QS if q["secret"]] == ["models.completion_key", "models.embedding_key",
                                                  "models.decision_key"]
    for q in QS:
        if q["secret"]:
            assert q["fills"] and all(t.split("#")[0].endswith((".env", ".env.server")) for t in q["fills"])


def test_custom_needs_go_to_custom_md():
    assert all(QS_BY_ID[i]["fills"] == [".bdc-assist-config/custom.md"] for i in ("tools.reshape", "tools.steps"))


def test_fixed_topics_skipped_on_no():
    assert QS_BY_ID["fixed.topics"]["skip_if"] == "fixed.wanted is no"


def test_every_target_documented_in_config_map():
    text = CONFIG_MAP.read_text(encoding="utf-8")
    missing = [t for q in QS for t in q["fills"] if f"`{t}`" not in text]
    assert not missing


def test_decision_model_asked_only_when_the_clone_supports_it():
    q = QS_BY_ID["models.decision"]
    assert q["default"] == "no" and "USE_DECISION_MODEL" in q["skip_if"]
    assert "bdc-assist/.env#USE_DECISION_MODEL" in q["fills"]


def test_refuse_rules_also_fill_the_decision_checklist():
    for i in ("project.purpose", "rules.refuse"):
        assert "bdc-assist/prompts.yaml#decision_input_guardrail" in QS_BY_ID[i]["fills"], i


def test_same_key_still_reaches_the_embedding_targets():
    # skipping the embedding key for "same key as the chat model" left doc-mcp without one
    assert "same key" not in QS_BY_ID["models.embedding_key"]["skip_if"]


def test_kubernetes_questions_only_for_kubernetes():
    for i in ("running.k8s_namespace", "running.k8s_registry", "running.k8s_host", "running.k8s_storage"):
        assert "Kubernetes" in QS_BY_ID[i]["skip_if"], i
    assert "Kubernetes" in QS_BY_ID["running.where"]["text"]
