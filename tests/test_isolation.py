"""Restricted MCP mode. All fixtures are synthetic: two throwaway vaults, `work` and `life`."""
import asyncio
import json
import os

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from wayfinder import corpus as C
from wayfinder import live
from wayfinder import methods as M
from wayfinder.mcp_server import create_server
from wayfinder.policy import Policy, PolicyError, from_options

SECRET = "LIFE-ONLY-SECRET"  # appears only in the disallowed vault


@pytest.fixture
def vaults(tmp_path, monkeypatch):
    work, life = tmp_path / "work", tmp_path / "life"
    (work / "ops").mkdir(parents=True)
    (life / "health").mkdir(parents=True)
    (work / "ops" / "deploys.md").write_text("---\ndescription: deploy runbook\n---\nDeploys roll through staging.\n")
    (work / "ops" / "oncall.md").write_text("On-call rotation and paging policy.\n")
    (life / "health" / "doctor.md").write_text(f"---\ndescription: {SECRET} appointment\n---\n{SECRET} deploys staging\n")
    config = tmp_path / "config.toml"
    config.write_text(f'[sources.work]\npath = "{work}"\n\n[sources.life]\npath = "{life}"\n')
    monkeypatch.setattr(C, "CONFIG", config)
    return work, life


def call(server, tool, **args):
    """(ok, text) for a tool call, as the client would see it."""
    try:
        result = asyncio.run(server.call_tool(tool, args))
        return True, json.dumps([c.text for c in result.content] if hasattr(result, "content") else result)
    except ToolError as e:
        return False, str(e)


def restricted(*names):
    return create_server(Policy.restrict(list(names)))


def test_allowed_source_retrieves(vaults):
    ok, text = call(restricted("work"), "retrieve", query="deploys staging", source="work")
    assert ok and "ops/deploys.md" in text and SECRET not in text


def test_single_allowed_source_is_the_default(vaults):
    ok, text = call(restricted("work"), "retrieve", query="deploys staging")
    assert ok and "ops/deploys.md" in text


def test_disallowed_source_is_refused_without_leaking(vaults):
    work, life = vaults
    ok, text = call(restricted("work"), "retrieve", query="deploys", source="life")
    assert not ok
    assert str(life) not in text and SECRET not in text
    _, unknown = call(restricted("work"), "retrieve", query="deploys", source="no-such-vault")
    assert text == unknown  # a disallowed name looks exactly like a name that doesn't exist


@pytest.mark.parametrize("arg", ["{life}", "{work}", "{work}/../life", "work/../life", "../life", "~", "/"])
def test_paths_and_traversal_are_rejected(vaults, arg):
    work, life = vaults
    ok, text = call(restricted("work"), "insert", text="deploys staging",
                    source=arg.format(work=work, life=life))
    assert not ok and SECRET not in text and str(life) not in text


def test_symlink_escapes_are_not_read(vaults):
    work, life = vaults
    os.symlink(life / "health" / "doctor.md", work / "ops" / "escape.md")  # file link out of the root
    os.symlink(life / "health", work / "linked-dir")                       # folder link out of the root
    ok, text = call(restricted("work"), "retrieve", query=f"{SECRET} appointment", source="work", k=20)
    assert ok and SECRET not in text and "escape.md" not in text and "linked-dir" not in text


def test_symlink_swapped_in_after_listing_is_not_read(vaults):
    work, life = vaults
    corpus = live.LiveCorpus(C.Source.resolve("work"))
    notes = dict(corpus.at())
    (work / "ops" / "oncall.md").unlink()
    os.symlink(life / "health" / "doctor.md", work / "ops" / "oncall.md")
    assert SECRET not in corpus.doc("ops/oncall.md", notes["ops/oncall.md"])


def test_list_sources_shows_only_allowed(vaults):
    work, life = vaults
    ok, text = call(restricted("work"), "list_sources")
    assert ok and "work" in text and "life" not in text and str(life) not in text


def test_packs_and_run_pack_respect_the_allowlist(vaults):
    server = restricted("work")
    assert not call(server, "list_packs", source="life")[0]
    assert not call(server, "run_pack", pack="notes-retrieve", text="x", source="life")[0]
    ok, text = call(server, "run_pack", pack="no-such-pack", text="x", source="work")
    assert not ok and "unknown pack" in text


def test_two_allowed_sources_need_an_explicit_choice(vaults):
    ok, text = call(restricted("work", "life"), "retrieve", query="deploys")
    assert not ok and "pass source" in text


def test_unexpected_errors_are_generic_in_restricted_mode(vaults, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError(f"/private/path {SECRET}")
    monkeypatch.setattr(live, "retrieve", boom)
    ok, text = call(restricted("work"), "retrieve", query="x", source="work")
    assert not ok and SECRET not in text and "/private/path" not in text


def test_source_that_disappears_fails_closed(vaults):
    work, _ = vaults
    server = restricted("work")
    work.rename(work.with_name("work-moved"))
    ok, text = call(server, "retrieve", query="deploys", source="work")
    assert not ok and "unavailable" in text


def test_source_root_swapped_for_a_symlink_fails_closed(vaults):
    work, life = vaults
    server = restricted("work")
    work.rename(work.with_name("work-old"))
    os.symlink(life, work)  # same configured path, now resolving into the other vault
    ok, text = call(server, "retrieve", query=SECRET, source="work")
    assert not ok and SECRET not in text


def test_cache_is_scoped_per_source(vaults, monkeypatch):
    torch = pytest.importorskip("torch")
    work, life = vaults
    for root, first, second in ((work, "apple", "pear"), (life, "pear", "apple")):
        (root / "same").mkdir()
        (root / "same" / "a.md").write_text(first * 3)
        (root / "same" / "b.md").write_text(second * 3)
        for name in ("a.md", "b.md"):  # identical relative paths and mtimes in both vaults
            os.utime(root / "same" / name, ns=(1_700_000_000_000_000_000,) * 2)
    monkeypatch.setattr(M, "embed", lambda texts: torch.nn.functional.normalize(
        torch.tensor([[t.count("apple") + .01, t.count("pear") + .01] for t in texts]), dim=-1))
    M._vectors.clear()
    for name, best in (("work", "same/a.md"), ("life", "same/b.md")):
        source = C.Source.resolve(name)
        corpus = live.LiveCorpus(source)
        notes = [n for n in corpus.at() if n[0].startswith("same/")]
        assert M.minilm(corpus, "apple", notes)[0][0] == best


def test_invalid_restricted_config_refuses_to_start(vaults, tmp_path):
    with pytest.raises(PolicyError):
        Policy.restrict([])
    with pytest.raises(PolicyError):
        Policy.restrict(["work", "not-configured"])
    with pytest.raises(PolicyError):
        Policy.restrict(["work"], {"sources": {"work": {"path": str(tmp_path / "missing")}}})
    with pytest.raises(PolicyError):
        from_options(allow=["work"], unrestricted=True)


def test_config_allowlist_restricts_and_never_falls_back(vaults):
    policy, warning = from_options(config={"mcp": {"allow": ["work"]},
                                           "sources": C.load_config()["sources"]})
    assert policy.restricted and policy.names() == ["work"] and warning is None
    with pytest.raises(PolicyError):  # a bad allowlist is an error, not unrestricted mode
        from_options(config={"mcp": {"allow": ["nope"]}, "sources": {}})


def test_unrestricted_mode_must_be_explicit(vaults):
    work, _ = vaults
    policy, warning = from_options(unrestricted=True)
    assert not policy.restricted and warning is None
    ok, text = call(create_server(policy), "retrieve", query="deploys", source=str(work))
    assert ok and "ops/deploys.md" in text  # dev mode keeps folder paths
    with pytest.raises(PolicyError, match="no allowlist"):  # nothing configured: refuse, never open
        from_options()


def test_insert_stays_read_only(vaults):
    work, _ = vaults
    before = {p: p.read_bytes() for p in work.rglob("*") if p.is_file()}
    ok, _ = call(restricted("work"), "insert", text="Deploys need a rollback plan.", source="work")
    assert ok and before == {p: p.read_bytes() for p in work.rglob("*") if p.is_file()}


def test_swap_between_listing_and_open_is_caught_on_the_descriptor(vaults, monkeypatch):
    """Simulate the race: the attacker swaps the note for a symlink at the very moment it is opened."""
    work, life = vaults
    corpus = live.LiveCorpus(C.Source.resolve("work"))
    notes = dict(corpus.at())
    target = work / "ops" / "oncall.md"
    real_open = os.open

    def racing_open(path, flags, *args, **kwargs):
        if str(path) == str(target):
            target.unlink()
            os.symlink(life / "health" / "doctor.md", target)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(live.os, "open", racing_open)
    assert SECRET not in corpus.doc("ops/oncall.md", notes["ops/oncall.md"])


def test_opened_path_reports_the_real_file(tmp_path):
    (tmp_path / "real.md").write_text("x")
    os.symlink(tmp_path / "real.md", tmp_path / "link.md")
    fd = os.open(tmp_path / "link.md", os.O_RDONLY)
    try:
        assert os.path.realpath(live._opened_path(fd)) == os.path.realpath(tmp_path / "real.md")
    finally:
        os.close(fd)
