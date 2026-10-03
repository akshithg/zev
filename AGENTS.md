# Project instructions

Keep only guidance that cannot be discovered elsewhere in this repository.
Remove duplicated or outdated instructions instead of maintaining a second
description of the code and workflow.

- `Zotero.Collections.getByLibrary()` includes trashed collections; filter on
  `!collection.deleted` unless they are explicitly wanted.
- Trashing a collection leaves its items in the library.
- `collection.addItem()` requires a transaction. To add membership outside a
  transaction, use `item.addToCollection(id)` and `await item.saveTx()`.
- Record metadata corrections as `bibtex:` blocks in versioned knowledge-vault
  notes rather than automatically overwriting Zotero metadata.
- Discuss changes to the bridge's security boundary with the maintainer before
  implementing them.
