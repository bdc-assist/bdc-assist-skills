import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent


def test_plugin_manifest():
    m = json.loads((ROOT / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
    assert m["name"] == "bdc-assist-skills" and m["version"] and m["description"]


def test_marketplace_lists_this_plugin():
    m = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text(encoding="utf-8"))
    assert m["name"] and m["owner"]["name"]
    assert [p["name"] for p in m["plugins"]] == ["bdc-assist-skills"] and m["plugins"][0]["source"] == "./"


@pytest.mark.parametrize("skill", sorted((ROOT / "skills").glob("*/SKILL.md")), ids=lambda p: p.parent.name)
def test_skill_frontmatter(skill):
    front = yaml.safe_load(skill.read_text(encoding="utf-8").split("---")[1])
    assert front["name"] == skill.parent.name
    assert front["description"].startswith("Use when") and len(front["description"]) <= 500
