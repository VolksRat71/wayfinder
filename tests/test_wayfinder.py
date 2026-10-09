import subprocess
import textwrap

import pytest

from wayfinder import evaluate as E
from wayfinder import methods as M
from wayfinder.corpus import GitCorpus, Source
from wayfinder.data import BUILDERS
from wayfinder.packs import Pack, discover

KUBE = "Kubernetes deploys roll out through the staging cluster before production.\n"
MORE = "Rollout of kubernetes pods waits for the readiness probe; a failed probe pauses the rollout.\n"
SOUP = "Tomato soup: roast tomatoes, garlic and onion, then blend with stock.\n"


def commit(repo, files, msg):
    for path, text in files.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text(text)
    subprocess.run(["git", "-C", repo, "add", "-A"], check=True)
    subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", msg], check=True)
    return subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


@pytest.fixture
def vault(tmp_path):
    subprocess.run(["git", "init", "-q", tmp_path], check=True)
    first = commit(tmp_path, {"ops/deploys.md": KUBE, "food/bread.md": "Sourdough needs a starter.\n"}, "seed")
    second = commit(tmp_path, {"ops/deploys.md": KUBE + MORE}, "update")
    commit(tmp_path, {"food/soup.md": SOUP}, "new note")
    return tmp_path, first, second


def test_git_inserts_labels_updates_and_new_notes(vault):
    path, first, second = vault
    rows = BUILDERS["git-inserts"](Source("t", path))
    update = next(r for r in rows if r["kind"] == "update")
    new = next(r for r in rows if r["kind"] == "new")
    assert update["truth"] == ["ops/deploys.md"] and update["snapshot"] == first
    assert new["truth"] == "food" and new["snapshot"] == second  # zero-config label = top-level folder


def test_bm25_ranks_the_matching_note_first(vault):
    path, first, _ = vault
    corpus = GitCorpus(Source("t", path))
    assert M.bm25(corpus, "kubernetes rollout", corpus.at(first))[0][0] == "ops/deploys.md"


def test_selective_accuracy_keeps_whole_tie_group():
    assert E.selective_accuracy([0.9, 0.9, 0.1, 0.1], [True, False, True, True], 0.25) == 0.5


def test_insert_eval_scores_the_update(vault):
    path, _, _ = vault
    pack = Pack("p", "", "insert", "git-inserts", methods=["bm25"])
    rows = E.evaluate(pack, Source("t", path), emit=lambda r: None)
    update = next(r for r in rows if r[1] == "insert_update")
    assert update[3] == 1 and update[4] == 1.0  # one row, hit@1


def test_source_pack_can_add_a_builder_and_method(vault):
    path, first, _ = vault
    pack_dir = path / ".wayfinder" / "packs" / "custom"
    pack_dir.mkdir(parents=True)
    (pack_dir / "pack.toml").write_text(textwrap.dedent("""\
        name = "custom"
        description = "test pack"
        action = "retrieve"
        dataset = "one-row"
        methods = ["alphabetical"]
        default = "alphabetical"
    """))
    (pack_dir / "pack.py").write_text(textwrap.dedent(f"""\
        open({str(path / "ran")!r}, "a").close()
        from wayfinder.data import builder
        from wayfinder.methods import register

        @builder("one-row")
        def one_row(source):
            return [{{"query": "anything", "truth": ["food/bread.md"], "snapshot": "{first}"}}]

        @register("alphabetical")
        def alphabetical(corpus, query, notes):
            return sorted(((rel, 0.0) for rel, _ in notes))
    """))
    assert "custom" not in discover(Source("t", path))  # untrusted: pack.py never runs
    assert not (path / "ran").exists()
    source = Source("t", path, trust_packs=True)
    pack = discover(source)["custom"]
    rows = E.evaluate(pack, source, emit=lambda r: None)
    assert rows[0][1:5] == ("retrieve", "alphabetical", 1, 1.0)  # food/bread.md sorts first


def test_live_retrieve_and_insert_read_the_working_tree(vault):
    from wayfinder import live
    path, _, _ = vault
    (path / "food" / "salad.md").write_text("Caesar salad: romaine, croutons, parmesan, anchovy dressing.\n")  # uncommitted
    source = Source("t", path)
    assert live.retrieve("caesar salad croutons", source)["notes"][0]["path"] == "food/salad.md"
    result = live.insert("Bread proofing: sourdough starter needs feeding before the dough.", source)
    assert result["notes"][0]["path"] == "food/bread.md"
    assert result["new_note_folder"]["folder"] == "food"


def test_mcp_server_registers_read_only_tools():
    import asyncio
    from wayfinder.mcp_server import create_server
    from wayfinder.policy import Policy
    tools = {t.name: t for t in asyncio.run(create_server(Policy.unrestricted()).list_tools())}
    assert {"retrieve", "insert", "list_sources", "list_packs", "run_pack"} <= tools.keys()
    assert all(t.annotations.read_only_hint for t in tools.values())


def test_insert_excludes_the_note_being_filed_and_votes_on_text(vault):
    from wayfinder import live
    path, _, _ = vault
    (path / "inbox.md").write_text("Kubernetes rollout waits for readiness probes in production.\n")
    result = live.insert((path / "inbox.md").read_text(), Source("t", path), exclude=["inbox.md"])
    assert all(n["path"] != "inbox.md" for n in result["notes"])
    assert result["new_note_folder"]["folder"] == "ops"  # recently edited food notes must not outvote the match


def test_obsidian_install_copies_plugin_and_never_writes_a_command(tmp_path):
    from wayfinder.cli import main
    (tmp_path / ".obsidian").mkdir()
    main(["obsidian-install", str(tmp_path)])
    dest = tmp_path / ".obsidian" / "plugins" / "wayfinder"
    assert {p.name for p in dest.iterdir()} == {"manifest.json", "main.js"}  # no data.json naming an executable
    with pytest.raises(SystemExit):
        main(["obsidian-install", str(tmp_path / "not-a-vault")])


def test_pick_never_chooses_a_baseline(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "STATE", tmp_path)
    pack = Pack("p", "", "retrieve", "x", methods=["recent", "bm25"], metric="recall@5")
    rows = [("s", "retrieve", "recent", 9, 0.4, 0.9, 0.6, ""), ("s", "retrieve", "bm25", 9, 0.3, 0.5, 0.4, "")]
    assert E.pick(pack, Source("t", tmp_path), rows) == "bm25"


def test_choice_pack_scores_methods_against_majority(vault):
    from wayfinder.data import builder
    path, _, _ = vault

    @builder("tiny-choice")
    def tiny(source):
        return [{"query": "blocked waiting on you", "truth": "follow_up"}, {"query": "all done", "truth": "done"},
                {"query": "done and merged", "truth": "done"}]

    @M.register("says-blocked")
    def says_blocked(corpus, query, labels):
        p = 0.9 if "blocked" in query else 0.1
        return sorted([("follow_up", p), ("done", 1 - p)], key=lambda x: -x[1])

    pack = Pack("c", "", "choice", "tiny-choice", methods=["says-blocked"], labels={"follow_up": "", "done": ""},
                per_source=False)
    rows = {(r[1], r[2]): r for r in E.evaluate(pack, None, emit=lambda r: None)}
    assert rows[("choice", "majority")][6] == 2 / 3
    assert rows[("choice", "says-blocked")][6] == 1.0
    assert rows[("choice/follow_up", "says-blocked")][3] == 1  # per-label recall rows


def test_all_manifests_share_one_version():
    import json
    import tomllib
    from pathlib import Path
    root = Path(__file__).parent.parent
    versions = {tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]} | {
        json.loads((root / p).read_text())["version"] for p in
        (".claude-plugin/plugin.json", ".codex-plugin/plugin.json", "src/wayfinder/obsidian_plugin/manifest.json")}
    assert len(versions) == 1, versions
