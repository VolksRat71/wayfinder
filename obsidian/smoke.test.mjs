// Drives the built plugin with a stub `obsidian` module against the real `wayfinder` CLI.
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { execFileSync } from "node:child_process";
import Module, { createRequire } from "node:module";

const vault = mkdtempSync(join(tmpdir(), "wayfinder-vault-"));
const write = (p, t) => { mkdirSync(join(vault, p, ".."), { recursive: true }); writeFileSync(join(vault, p), t); };
write("ops/deploys.md", "Kubernetes deploys roll out through staging before production.\n");
write("food/bread.md", "Sourdough needs a fed starter and a long proof.\n");
write("food/soup.md", "Tomato soup: roast tomatoes and garlic, blend with stock.\n");

const seen = { notices: [], modals: [], opened: [] };
class Plugin { constructor(app) { this.app = app; this.commands = {}; }
  addCommand(c) { this.commands[c.id] = c; } addSettingTab() {} async loadData() { return null; } async saveData() {} }
class SuggestModal { constructor(app) { this.app = app; } setPlaceholder(p) { this.placeholder = p; } open() { seen.modals.push(this); } }
const stub = { Plugin, SuggestModal, PluginSettingTab: class {}, Setting: class {}, MarkdownView: class {}, FileSystemAdapter: class {},
  Notice: class { constructor(m) { seen.notices.push(m); } } };
const load = Module._load;
Module._load = function (req, ...rest) { return req === "obsidian" ? stub : load.call(this, req, ...rest); };

const Wayfinder = createRequire(import.meta.url)("../src/wayfinder/obsidian_plugin/main.js").default;
let active = { path: "food/bread.md" };
const app = { vault: { adapter: { getBasePath: () => vault }, cachedRead: async (f) => readFileSync(join(vault, f.path), "utf8") },
  workspace: { getActiveFile: () => active, getActiveViewOfType: () => null, openLinkText: (p) => seen.opened.push(p) } };
const plugin = new Wayfinder(app);
await plugin.onload();
plugin.settings.command = execFileSync("which", ["wayfinder"]).toString().trim();

test("related notes lists the matching note, never the active one, and opens it", async () => {
  await plugin.commands["related-notes"].callback();
  const items = seen.modals.at(-1).getSuggestions("");
  assert.equal(items[0].note.path, "food/soup.md");
  assert.ok(!items.some((i) => i.note?.path === "food/bread.md"));
  seen.modals.at(-1).onChooseSuggestion(items[0]);
  assert.deepEqual(seen.opened, ["food/soup.md"]);
});

test("where does this go suggests existing notes plus a new-note folder", async () => {
  active = { path: "inbox.md" };
  write("inbox.md", "Kubernetes rollout waits for readiness probes in production.\n");
  await plugin.commands["where-does-this-go"].callback();
  const items = seen.modals.at(-1).getSuggestions("");
  assert.equal(items[0].note.path, "ops/deploys.md");
  assert.equal(items.at(-1).folder, "ops");
});

test("a missing CLI is reported, not thrown", async () => {
  plugin.settings.command = "/nonexistent/wayfinder";
  await plugin.commands["related-notes"].callback();
  assert.match(seen.notices.at(-1), /not found/);
});
