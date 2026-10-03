# zev

Evaluate JavaScript inside a running Zotero, from the command line.

That is the whole tool. There are no per-operation commands for tagging, filing,
or metadata — an agent writes the JavaScript it needs at the moment it needs it,
against Zotero's own API, which is far richer than any fixed tool surface.

```console
$ echo 'const items = await Zotero.Items.getAll(Zotero.Libraries.userLibraryID);
        return JSON.stringify({top: items.filter(i => i.isTopLevelItem()).length});' \
  | zev eval
{
  "top": 642
}
```

zev is the *hands*. Reading and analysing a library is a separate concern —
that belongs to `corpus`, which builds a queryable SQLite view of Zotero and
never writes to it.

## Requirements

- Python 3.10+
- Zotero desktop running (Zotero 8 is the default target; Zotero 7 also works)
- The zev-bridge plugin installed

## Install

Install directly from this GitHub repository:

```console
uv tool install git+https://github.com/akshithg/zev.git
zev setup --download-only     # prints the bundled XPI path
```

Install that XPI **once** through Zotero: *Tools > Plugins > gear >
Install Add-on From File*. Zotero is Firefox-based and Firefox no longer
auto-installs sideloaded add-ons, so a first install has to go through the UI.

After that, upgrades are one command:

```console
zev setup --install-profile --restart   # quits Zotero, installs, relaunches, waits
zev doctor
```

The bridge is a small Zotero plugin that listens on `127.0.0.1:24119` and
evaluates posted code in Zotero's privileged context.

## Usage

```console
zev eval script.js        # from a file
zev eval < script.js      # from stdin
zev eval script.js --raw  # show the bridge envelope, not just the return value
zev doctor                # check Zotero and the bridge
```

### Writing the JavaScript

The plugin wraps your code in `(async () => { ... })()`, so send a **bare
statement body ending in `return JSON.stringify(...)`**. Do not add your own
wrapper: an unawaited inner function can lose the return value and its errors.

```js
const lib = Zotero.Libraries.userLibraryID;
const item = Zotero.Items.getByLibraryAndKey(lib, "ABCD1234");
item.addToCollection(collectionID);
await item.saveTx();          // saveTx, not save, outside a transaction
return JSON.stringify({ok: true});
```

Most of the Zotero API is async. `Zotero.Items.getAll()` returns a promise;
use `await` before working with the returned items.

## Safety

zev writes to a store with **no field-level undo**, and Zotero's file sync
propagates changes to the server. The tool deliberately provides no guardrails,
so the discipline lives with the caller:

1. **Snapshot first.** Record the current state of whatever you are about to
   touch, before you touch it. Usually a few lines of SQL against `corpus.db`.
2. **Prefer additive.** Adding a collection membership is trivially undoable;
   removing one loses information. Adding beats moving beats deleting.
3. **Verify with a second reader.** Re-run `corpus sync` and confirm the change
   through a tool that did not perform it.

## Development

```console
make test                       # unittest
make build                      # rebuild the bridge XPI
ruff check . && ruff format .
```

No runtime dependencies.

## Credits

zev is derived from [**zoty**](https://github.com/eric-tramel/zoty) by
**Eric Tramel**, MIT licensed. That is not a footnote — most of what makes this
work is his:

- **`zotero-plugin/bootstrap.js`** — the bridge itself. The `nsIServerSocket`
  listener and the privileged-eval wrapper are the reason any of this is
  possible, and they are Eric's design. This repo changed the response encoding
  and little else.
- **`src/zev/setup.py`** — profile discovery, XPI inspection, and the install
  and diagnostics flow.
- **`src/zev/bridge.py`** — the HTTP client for the bridge endpoint.
- **`scripts/build_zotero_plugin.py`**, the `Makefile`, and the release
  tooling.

What this fork changed: removed the search index, MCP server, citation tools,
and canned mutation tools in favour of a single `eval` primitive; fixed UTF-8
encoding in the bridge response path; added automated install-and-restart.

Reading and analysis belong in the separate `corpus` project.
