// Wayfinder for Obsidian: a thin client of the local `wayfinder` CLI (no server, no network).
import { App, FileSystemAdapter, MarkdownView, Notice, Plugin, PluginSettingTab, Setting, SuggestModal } from "obsidian";
import { execFile } from "child_process";
import { homedir } from "os";
import { join } from "path";

interface Settings { command: string; k: number }
// GUI apps on macOS don't get the shell PATH, so default to where `uv tool install` puts it.
const DEFAULTS: Settings = { command: join(homedir(), ".local", "bin", "wayfinder"), k: 8 };
const MAX_CHARS = 4000;

interface Note { path: string; score: number; description: string }
interface Result { method: string; notes: Note[]; new_note_folder?: { folder: string; confidence: number } | null }
type Item = { note: Note } | { folder: string; confidence: number };

export default class Wayfinder extends Plugin {
  settings: Settings = DEFAULTS;

  async onload() {
    this.settings = Object.assign({}, DEFAULTS, await this.loadData());
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
      const child = execFile(this.settings.command, full, { timeout: 60_000, maxBuffer: 10 * 1024 * 1024 },
        (err, stdout, stderr) => {
          if (err) {
            const missing = (err as NodeJS.ErrnoException).code === "ENOENT";
            reject(new Error(missing ? `wayfinder CLI not found at ${this.settings.command}; set the path in settings.`
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
      .setDesc("Full path to the wayfinder CLI (uv tool install puts it in ~/.local/bin).")
      .addText((t) => t.setValue(this.plugin.settings.command).onChange(async (v) => {
        this.plugin.settings.command = v.trim();
        await this.plugin.saveData(this.plugin.settings);
      }));
    new Setting(this.containerEl)
      .setName("Results")
      .setDesc("How many notes to show.")
      .addText((t) => t.setValue(String(this.plugin.settings.k)).onChange(async (v) => {
        const k = parseInt(v, 10);
        if (k > 0) { this.plugin.settings.k = k; await this.plugin.saveData(this.plugin.settings); }
      }));
  }
}
