.PHONY: all clean fetcher-test check-release

TAG ?= $(shell git describe --tags --always 2>/dev/null || echo dev)

all: dist/lexicons.json

dist/lexicons.json: build.py
	mkdir -p dist
	python3 build.py --out dist --version $(TAG)

LANG:
	@echo "use: make build-lang LANG=de"

build-lang:
	mkdir -p dist
	python3 build.py --out dist --version $(TAG) --langs $(LANG)

fetcher-test:
	cargo test --workspace

# Full local pre-release gate (what CI used to do, offline + deeper):
# crate tests, lints, manifest/bundle/resolution validation, and the
# consumer smoke over the locally built dist/ tree.
check-release:
	cargo test --quiet
	cargo clippy --all-targets -- -D warnings
	python3 scripts/validate_release.py
	cargo run --release --quiet --example consumer_smoke

clean:
	rm -rf dist target
