"use strict";
var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __hasOwnProp = Object.prototype.hasOwnProperty;
var __export = (target, all) => {
  for (var name in all)
    __defProp(target, name, { get: all[name], enumerable: true });
};
var __copyProps = (to, from, except, desc) => {
  if (from && typeof from === "object" || typeof from === "function") {
    for (let key of __getOwnPropNames(from))
      if (!__hasOwnProp.call(to, key) && key !== except)
        __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
  }
  return to;
};
var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);

// main.ts
var main_exports = {};
__export(main_exports, {
  ResultsModal: () => ResultsModal,
  default: () => Wayfinder
});
module.exports = __toCommonJS(main_exports);
var import_obsidian = require("obsidian");
var import_child_process = require("child_process");
var import_os = require("os");
var import_path = require("path");
var DEFAULTS = { command: (0, import_path.join)((0, import_os.homedir)(), ".local", "bin", "wayfinder"), k: 8 };
var MAX_CHARS = 4e3;
var Wayfinder = class extends import_obsidian.Plugin {
  constructor() {
    super(...arguments);
    this.settings = DEFAULTS;
  }
  async onload() {
    this.settings = Object.assign({}, DEFAULTS, await this.loadData());
    this.addSettingTab(new WayfinderSettings(this.app, this));
    this.addCommand({ id: "related-notes", name: "Related notes", callback: () => this.related() });
    this.addCommand({ id: "where-does-this-go", name: "Where does this go?", callback: () => this.where() });
  }
  /** The selection if there is one, else the active note's text. */
  async input() {
    const file = this.app.workspace.getActiveFile();
    const selection = this.app.workspace.getActiveViewOfType(import_obsidian.MarkdownView)?.editor.getSelection();
    const text = selection || (file ? await this.app.vault.cachedRead(file) : "");
    if (!text.trim()) {
      new import_obsidian.Notice("Wayfinder: open a note or select some text first.");
      return null;
    }
    return { text: text.slice(0, MAX_CHARS), self: file?.path };
  }
  exclude(path) {
    return path ? ["--exclude", path] : [];
  }
  run(args, stdin) {
    const vault = this.app.vault.adapter.getBasePath();
    const full = [...args, "--source", vault, "-k", String(this.settings.k), "--json"];
    return new Promise((resolve, reject) => {
      const child = (0, import_child_process.execFile)(
        this.settings.command,
        full,
        { timeout: 6e4, maxBuffer: 10 * 1024 * 1024 },
        (err, stdout, stderr) => {
          if (err) {
            const missing = err.code === "ENOENT";
            reject(new Error(missing ? `wayfinder CLI not found at ${this.settings.command}; set the path in settings.` : (stderr || err.message).trim().split("\n").pop()));
          } else {
            try {
              resolve(JSON.parse(stdout));
            } catch {
              reject(new Error("wayfinder returned something that isn't JSON."));
            }
          }
        }
      );
      if (stdin !== void 0) child.stdin?.end(stdin);
    });
  }
  async related() {
    const input = await this.input();
    if (!input) return;
    try {
      const result = await this.run(["retrieve", input.text, ...this.exclude(input.self)]);
      const items = result.notes.map((note) => ({ note }));
      new ResultsModal(this.app, items, `Related notes (${result.method})`).open();
    } catch (e) {
      new import_obsidian.Notice(`Wayfinder: ${e.message}`);
    }
  }
  async where() {
    const input = await this.input();
    if (!input) return;
    try {
      const result = await this.run(["insert", "-", ...this.exclude(input.self)], input.text);
      const items = result.notes.map((note) => ({ note }));
      if (result.new_note_folder) items.push(result.new_note_folder);
      new ResultsModal(this.app, items, `Where this belongs (${result.method})`).open();
    } catch (e) {
      new import_obsidian.Notice(`Wayfinder: ${e.message}`);
    }
  }
};
var ResultsModal = class extends import_obsidian.SuggestModal {
  constructor(app, items, placeholder) {
    super(app);
    this.items = items;
    this.setPlaceholder(placeholder);
  }
  getSuggestions(query) {
    const q = query.toLowerCase();
    return this.items.filter((i) => ("note" in i ? i.note.path : i.folder).toLowerCase().includes(q));
  }
  renderSuggestion(item, el) {
    if ("note" in item) {
      el.createEl("div", { text: item.note.path.replace(/\.md$/, "") });
      el.createEl("small", { text: item.note.description || `score ${item.note.score.toFixed(2)}` });
    } else {
      el.createEl("div", { text: `New note in ${item.folder}/` });
      el.createEl("small", { text: `confidence ${item.confidence.toFixed(2)}` });
    }
  }
  onChooseSuggestion(item) {
    if ("note" in item) this.app.workspace.openLinkText(item.note.path, "", false);
    else new import_obsidian.Notice(`Wayfinder: create the new note in ${item.folder}/`);
  }
};
var WayfinderSettings = class extends import_obsidian.PluginSettingTab {
  constructor(app, plugin) {
    super(app, plugin);
    this.plugin = plugin;
  }
  display() {
    this.containerEl.empty();
    new import_obsidian.Setting(this.containerEl).setName("wayfinder command").setDesc("Full path to the wayfinder CLI (uv tool install puts it in ~/.local/bin).").addText((t) => t.setValue(this.plugin.settings.command).onChange(async (v) => {
      this.plugin.settings.command = v.trim();
      await this.plugin.saveData(this.plugin.settings);
    }));
    new import_obsidian.Setting(this.containerEl).setName("Results").setDesc("How many notes to show.").addText((t) => t.setValue(String(this.plugin.settings.k)).onChange(async (v) => {
      const k = parseInt(v, 10);
      if (k > 0) {
        this.plugin.settings.k = k;
        await this.plugin.saveData(this.plugin.settings);
      }
    }));
  }
};
// Annotate the CommonJS export names for ESM import in node:
0 && (module.exports = {
  ResultsModal
});
