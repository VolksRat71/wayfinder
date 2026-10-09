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
