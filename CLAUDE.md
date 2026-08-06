# CLAUDE.md — zev

zev evaluates JavaScript inside a running Zotero. One command, `zev eval`.
It is the write half of a two-project split:

- **zev** — the hands. Writes to Zotero via the bridge plugin. No fixed
  operations; the agent composes JS just in time.
- **corpus** — the head. Builds a disposable SQLite view of Zotero and the
  knowledge vault. Reads only, opens `zotero.sqlite` with `immutable=1`.

Anything that reads or analyses belongs in corpus, not here. If you find
yourself adding a query to zev, it is in the wrong repo.

## Layout

```
src/zev/bridge.py    bridge client (POST 127.0.0.1:24119/execute)
src/zev/cli.py       eval / doctor / setup
src/zev/setup.py     plugin install and diagnostics
zotero-plugin/        the bridge itself (bootstrap.js)
```

## Bridge JS contract (critical)

`bootstrap.js` wraps posted code in its own `(async () => { … })()`. Code you
send must be a **bare statement body ending in `return JSON.stringify(...)`** —
do **not** self-wrap in another IIFE. Double-wrapping discards the return value
and swallows errors.

Other things that bite:

- Most of the Zotero API is async. `Zotero.Items.getAll()` returns a promise;
  a missing `await` yields `undefined` rather than an error.
- Use `item.saveTx()` outside a transaction, `item.save()` inside one. The bare
  `collection.addItem` needs a transaction; `item.addToCollection(id)` plus
  `await item.saveTx()` does not.
- `Zotero.Collections.getByLibrary()` includes trashed collections. Filter on
  `!c.deleted` unless you mean to include them.

## Rules and lessons (don't relearn the hard way)

- **Zotero has no field-level undo, and file sync propagates bad writes to the
  server.** Snapshot the affected state to a file before any bulk write. Prefer
  additive changes; adding beats moving beats deleting.
- **Verify with a second reader.** After a write, re-run `corpus sync` and check
  the result through a tool that did not perform the write.
- **Trashing a collection does not trash its items.** They become orphans that
  are invisible in the sidebar and reachable only through All Items or search.
- **Metadata corrections do not belong in Zotero.** Record them as a `bibtex:`
  block in the paper's note in the knowledge vault, where they are versioned and
  reversible. Identifier-free items (webpages, repos, some conference papers)
  are exactly where automated metadata tools attach the wrong paper.

- **A new plugin id cannot be sideloaded.** Copying an XPI into
  `profile/extensions/` only upgrades an addon Zotero already registered;
  `extensions.autoDisableScopes` defaults to 15, so a first install must go
  through Tools > Plugins. `zev setup --install-profile` refuses when the id is
  unregistered rather than quitting Zotero for an install that cannot work.

## Dev

- Python 3.10+ (3.13 recommended) via `uv`. No runtime dependencies.
- Tests: `make test`. Plugin: `make build` (honours `$PYTHON`).
- Lint: `ruff check .`, `ruff format .`, `ty check src`. `line-length = 120`.
