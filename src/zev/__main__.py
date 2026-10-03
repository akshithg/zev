"""Allow `python -m zev` to use the zev CLI."""

from zev.cli import main

raise SystemExit(main())
