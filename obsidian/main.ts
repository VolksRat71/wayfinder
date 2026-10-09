// Wayfinder for Obsidian: a thin client of the local `wayfinder` CLI (no server, no network).
import { App, FileSystemAdapter, MarkdownView, Notice, Plugin, PluginSettingTab, Setting, SuggestModal } from "obsidian";
import { execFile } from "child_process";
import { existsSync } from "fs";
import { homedir } from "os";
import { join } from "path";

// Which executable runs must never come from the vault: data.json can be synced or committed by
// someone else. So the CLI path lives in this device's localStorage, never in plugin data.
// GUI apps on macOS don't get the shell PATH, so look where `uv tool install` / Homebrew put it.
const COMMAND_KEY = "wayfinder-command";
const CANDIDATES = [join(homedir(), ".local", "bin", "wayfinder"), "/opt/homebrew/bin/wayfinder", "/usr/local/bin/wayfinder"];

interface Settings { k: number }
const DEFAULTS: Settings = { k: 8 };
const MAX_CHARS = 4000;

interface Note { path: string; score: number; description: string }
interface Result { method: string; notes: Note[]; new_note_folder?: { folder: string; confidence: number } | null }
type Item = { note: Note } | { folder: string; confidence: number };

export default class Wayfinder extends Plugin {
  settings: Settings = DEFAULTS;

  /** The CLI to run: this device's override, else the first standard install location found. */
  command(): string {
    return window.localStorage.getItem(COMMAND_KEY) || CANDIDATES.find((p) => existsSync(p)) || CANDIDATES[0];
  }

  setCommand(path: string) {
    if (path) window.localStorage.setItem(COMMAND_KEY, path);
    else window.localStorage.removeItem(COMMAND_KEY);
  }

  async onload() {
    const data = await this.loadData();  // only `k` is read; anything else in data.json is ignored
    this.settings = { k: Number(data?.k) > 0 ? Number(data.k) : DEFAULTS.k };
    this.addSettingTab(new WayfinderSettings(this.app, this));
    this.addCommand({ id: "related-notes", name: "Related notes", callback: () => this.related() });
    this.addCommand({ id: "where-does-this-go", name: "Where does this go?", callback: () => this.where() });
  }

  /** The selection if there is one, else the active note's text. */
  private async input(): Promise<{ text: string; self?: string } | null> {
    const file = this.app.workspace.getActiveFile();
    const selection = this.app.workspace.getActiveViewOfType(MarkdownView)?.editor.getSelection();
    const text = selection || (file ? await this.app.vault.cachedRead(file) : "");
    if (!text.trim()) {
      new Notice("Wayfinder: open a note or select some text first.");
      return null;
    }
    return { text: text.slice(0, MAX_CHARS), self: file?.path };
  }

  private exclude(path?: string): string[] {
    return path ? ["--exclude", path] : [];
  }

  private run(args: string[], stdin?: string): Promise<Result> {
    const vault = (this.app.vault.adapter as FileSystemAdapter).getBasePath();
    const full = [...args, "--source", vault, "-k", String(this.settings.k), "--json"];
    return new Promise((resolve, reject) => {
      const command = this.command();
      const child = execFile(command, full, { timeout: 60_000, maxBuffer: 10 * 1024 * 1024 },
        (err, stdout, stderr) => {
          if (err) {
            const missing = (err as NodeJS.ErrnoException).code === "ENOENT";
            reject(new Error(missing ? `wayfinder CLI not found at ${command}; set the path in settings.`
                                     : (stderr || err.message).trim().split("\n").pop()));
          } else {
            try { resolve(JSON.parse(stdout)); } catch { reject(new Error("wayfinder returned something that isn't JSON.")); }
          }
        });
      if (stdin !== undefined) child.stdin?.end(stdin);
    });
  }

  async related() {
    const input = await this.input();
    if (!input) return;
    try {
      const result = await this.run(["retrieve", input.text, ...this.exclude(input.self)]);
      const items: Item[] = result.notes.map((note) => ({ note }));
      new ResultsModal(this.app, items, `Related notes (${result.method})`).open();
    } catch (e) {
      new Notice(`Wayfinder: ${(e as Error).message}`);
    }
  }

  async where() {
    const input = await this.input();
    if (!input) return;
    try {
      const result = await this.run(["insert", "-", ...this.exclude(input.self)], input.text);
      const items: Item[] = result.notes.map((note) => ({ note }));
      if (result.new_note_folder) items.push(result.new_note_folder);
      new ResultsModal(this.app, items, `Where this belongs (${result.method})`).open();
    } catch (e) {
      new Notice(`Wayfinder: ${(e as Error).message}`);
    }
  }
}

export class ResultsModal extends SuggestModal<Item> {
  constructor(app: App, private items: Item[], placeholder: string) {
    super(app);
    this.setPlaceholder(placeholder);
  }

  getSuggestions(query: string): Item[] {
    const q = query.toLowerCase();
    return this.items.filter((i) => ("note" in i ? i.note.path : i.folder).toLowerCase().includes(q));
  }

  renderSuggestion(item: Item, el: HTMLElement) {
    if ("note" in item) {
      el.createEl("div", { text: item.note.path.replace(/\.md$/, "") });
      el.createEl("small", { text: item.note.description || `score ${item.note.score.toFixed(2)}` });
    } else {
      el.createEl("div", { text: `New note in ${item.folder}/` });
      el.createEl("small", { text: `confidence ${item.confidence.toFixed(2)}` });
    }
  }

  onChooseSuggestion(item: Item) {
    if ("note" in item) this.app.workspace.openLinkText(item.note.path, "", false);
    else new Notice(`Wayfinder: create the new note in ${item.folder}/`);
  }
}

class WayfinderSettings extends PluginSettingTab {
  constructor(app: App, private plugin: Wayfinder) { super(app, plugin); }

  display() {
    this.containerEl.empty();
    new Setting(this.containerEl)
      .setName("wayfinder command")
      .setDesc("Full path to the wayfinder CLI. Leave empty to use ~/.local/bin, /opt/homebrew/bin or /usr/local/bin. " +
               "Stored on this device only, never in the vault.")
      .addText((t) => t.setPlaceholder(this.plugin.command()).setValue(window.localStorage.getItem(COMMAND_KEY) ?? "")
        .onChange((v) => this.plugin.setCommand(v.trim())));
    new Setting(this.containerEl)
      .setName("Results")
      .setDesc("How many notes to show.")
      .addText((t) => t.setValue(String(this.plugin.settings.k)).onChange(async (v) => {
        const k = parseInt(v, 10);
        if (k > 0) { this.plugin.settings.k = k; await this.plugin.saveData(this.plugin.settings); }
      }));
  }
}
