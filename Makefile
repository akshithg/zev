.PHONY: build release-build verify-build test clean

PYTHON ?= $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; else command -v python3; fi)
XPI := zotero-plugin/dist/zev-bridge.xpi
UPDATE_MANIFEST := zotero-plugin/dist/zev-bridge-updates.json

build:
	$(PYTHON) scripts/build_zotero_plugin.py

release-build:
	test -n "$(RELEASE_TAG)"
	$(PYTHON) scripts/build_zotero_plugin.py --release-tag "$(RELEASE_TAG)"

verify-build: build
	git diff --exit-code -- src/zev/assets/zev-bridge.xpi

test:
	node --test tests/test_plugin_http.cjs
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests -v

clean:
	rm -f $(XPI) $(UPDATE_MANIFEST)
