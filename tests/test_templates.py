from pathlib import Path

import yaml

TEMPLATES = Path(__file__).resolve().parent.parent / "skills/bdc-assist-init/templates"
COMPOSE = TEMPLATES / "deploy/docker-compose.yml"
DOCKERFILE = TEMPLATES / "deploy/Dockerfile"
DOCKERIGNORE = TEMPLATES / "deploy/Dockerfile.dockerignore"
GITIGNORE = TEMPLATES / "gitignore"


def lines(path: Path) -> list[str]:
    return [l.strip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]


def services() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]


def test_services():
    assert set(services()) == {"doc-mcp", "bdc-assist", "builder"}


def test_only_bot_publishes_a_port():
    C = services()
    assert [s for s in C if "ports" in C[s]] == ["bdc-assist"]
    assert C["bdc-assist"]["ports"] == ["${API_PORT:-8010}:8010"]


def test_builder_is_one_off():
    assert services()["builder"]["profiles"] == ["build"]


def test_doc_mcp_db_volume():
    assert any(v.endswith(":/data/chroma") for v in services()["doc-mcp"]["volumes"])


def test_env_files():
    C = services()
    assert {s: C[s]["env_file"] for s in C} == {"doc-mcp": ["bdc-doc-mcp.env.server"],
                                                "bdc-assist": ["bdc-assist.env.server"],
                                                "builder": ["bdc-doc-builder.env.server"]}


def test_container_plumbing():
    C = services()
    assert {"CONFIG_DIR": "/config", "MCP_HOST": "0.0.0.0", "MCP_PORT": "8001",
            "DB_PATH": "/data/chroma"}.items() <= C["doc-mcp"]["environment"].items()
    assert {"CONFIG_DIR": "/config", "R_DOC_MCP_URL": "http://doc-mcp:8001/mcp"}.items() <= C["bdc-assist"]["environment"].items()
    assert {"CONFIG_DIR": "/project/config/bdc-doc-builder", "DOC_MCP_URL": "http://doc-mcp:8001",
            "PREPROC_DATA_DIR": "/work/build/", "REPOS_DIR": "/work/repos/"}.items() <= C["builder"]["environment"].items()


def test_config_mounted_read_only():
    C = services()
    assert "../config/bdc-doc-mcp:/config:ro" in C["doc-mcp"]["volumes"]
    assert "../config/bdc-assist:/config:ro" in C["bdc-assist"]["volumes"]
    assert "..:/project:ro" in C["builder"]["volumes"]


def test_each_service_builds_its_clone_with_the_shared_dockerfile():
    C = services()
    repos = {"doc-mcp": "bdc-doc-mcp", "bdc-assist": "bdc-assist", "builder": "bdc-doc-builder"}
    assert {s: C[s]["build"] for s in C} == {s: {"context": f"../{r}", "dockerfile": "../deploy/Dockerfile"}
                                            for s, r in repos.items()}


def test_host_gateway_everywhere():
    C = services()
    assert all("host.docker.internal:host-gateway" in C[s]["extra_hosts"] for s in C)


def test_dockerignore_keeps_secrets_out():
    assert {".env", ".env.*", ".venv", ".git", "data", ".chroma_db"} <= set(lines(DOCKERIGNORE))


def test_dockerfile_runs_from_the_synced_venv():
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "uv sync --frozen --no-dev" in text and '/app/.venv/bin' in text
    assert not any("uv run" in str(services()[s].get("command", "")) for s in services())


def test_dockerfile_refuses_an_env_file_in_the_context():
    # the classic builder ignores Dockerfile.dockerignore: then a clone's .env (API keys) would be copied in
    text = DOCKERFILE.read_text(encoding="utf-8")
    copy, guard, sync = text.index("COPY . ."), text.index("test ! -e .env"), text.index("uv sync")
    assert copy < guard < sync


def test_setup_md_has_the_powershell_fallback():
    assert "powershell -ExecutionPolicy Bypass -File .\\demo_services.ps1" in (TEMPLATES / "SETUP.md").read_text(encoding="utf-8")


def test_gitignore():
    assert {"/bdc-assist/", "/bdc-doc-mcp/", "/bdc-doc-builder/", "/data/", "/deploy/*.env.server",
            "__pycache__/", ".pytest_cache/"} <= set(lines(GITIGNORE))  # custom code and its tests run in config/


def test_deploy_env_has_only_interpolation_values():
    values = dict(l.split("=", 1) for l in lines(TEMPLATES / "deploy/env"))
    assert values == {"API_PORT": "8010", "BUILD_FLAGS": ""}


def test_setup_md_sections():
    text = (TEMPLATES / "SETUP.md").read_text(encoding="utf-8")
    for heading in ("## Prerequisites", "## What was set up", "## Start the services", "## Build the content",
                    "## Chat with the bot", "## Check the setup", "## Deploy to a server", "## Change the setup",
                    "## Custom code", "## Where things are"):
        assert heading in text, heading


K8S = TEMPLATES / "deploy/k8s"
FILL = {"NAMESPACE": "demo", "IMAGE_REGISTRY": "ghcr.io/acme", "IMAGE_TAG": "1.0", "STORAGE_SIZE": "5Gi",
        "BOT_HOST": "bot.example.org"}


def k8s_docs(name: str) -> list[dict]:
    text = (K8S / name).read_text(encoding="utf-8")
    for key, value in FILL.items():
        text = text.replace("${" + key + "}", value)
    return [d for d in yaml.safe_load_all(text) if d]


def k8s_kind(name: str, kind: str) -> dict:
    return next(d for d in k8s_docs(name) if d["kind"] == kind)


def container(name: str) -> dict:
    return k8s_kind(name, "Deployment")["spec"]["template"]["spec"]["containers"][0]


def test_k8s_fill_ins_are_the_documented_ones():
    import re
    found = {m for f in K8S.glob("*.yaml") for m in re.findall(r"\$\{(\w+)\}", f.read_text(encoding="utf-8"))}
    assert found == set(FILL)


def test_k8s_every_object_in_the_namespace():
    assert all(d["metadata"]["namespace"] == "demo" for f in K8S.glob("*.yaml") for d in k8s_docs(f.name))


def test_k8s_doc_mcp_is_one_copy_with_its_disk():
    deployment = k8s_kind("doc-mcp.yaml", "Deployment")
    assert deployment["spec"]["replicas"] == 1 and deployment["spec"]["strategy"]["type"] == "Recreate"
    claim = k8s_kind("doc-mcp.yaml", "PersistentVolumeClaim")
    assert claim["spec"]["resources"]["requests"]["storage"] == "5Gi"
    mounts = {m["mountPath"]: m["name"] for m in container("doc-mcp.yaml")["volumeMounts"]}
    volumes = {v["name"]: v for v in deployment["spec"]["template"]["spec"]["volumes"]}
    assert volumes[mounts["/data/chroma"]]["persistentVolumeClaim"]["claimName"] == claim["metadata"]["name"]


def test_k8s_secrets_and_config_by_name():
    for name, secret, config in (("doc-mcp.yaml", "bdc-doc-mcp-env", "bdc-doc-mcp-config"),
                                 ("bdc-assist.yaml", "bdc-assist-env", "bdc-assist-config")):
        c = container(name)
        assert c["envFrom"] == [{"secretRef": {"name": secret}}]
        volumes = k8s_kind(name, "Deployment")["spec"]["template"]["spec"]["volumes"]
        assert {"name": "config", "configMap": {"name": config}} in volumes
        assert {"name": "config", "mountPath": "/config", "readOnly": True} in c["volumeMounts"]


def test_k8s_images_from_the_registry():
    assert container("doc-mcp.yaml")["image"] == "ghcr.io/acme/bdc-doc-mcp:1.0"
    assert container("bdc-assist.yaml")["image"] == "ghcr.io/acme/bdc-assist:1.0"


def test_k8s_container_plumbing():
    def env(name):
        return {e["name"]: e["value"] for e in container(name)["env"]}
    assert {"CONFIG_DIR": "/config", "MCP_HOST": "0.0.0.0", "MCP_PORT": "8001",
            "DB_PATH": "/data/chroma"}.items() <= env("doc-mcp.yaml").items()
    assert {"CONFIG_DIR": "/config", "R_DOC_MCP_URL": "http://doc-mcp:8001/mcp"}.items() <= env("bdc-assist.yaml").items()


def test_k8s_doc_mcp_stays_inside_the_cluster():
    assert k8s_kind("doc-mcp.yaml", "Service")["spec"].get("type", "ClusterIP") == "ClusterIP"
    rule = k8s_kind("ingress.yaml", "Ingress")["spec"]["rules"][0]
    assert rule["host"] == "bot.example.org"
    assert rule["http"]["paths"][0]["backend"]["service"] == {"name": "bdc-assist", "port": {"number": 8010}}


def test_setup_md_has_a_kubernetes_section():
    text = (TEMPLATES / "SETUP.md").read_text(encoding="utf-8")
    assert "## Deploy to Kubernetes" in text and "port-forward svc/doc-mcp 18001:8001" in text
    assert "envfile.py\" run" in text
