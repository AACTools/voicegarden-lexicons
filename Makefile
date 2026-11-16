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
# crate tests, lints, manifest/bundle/resolution validation with the
# expand-only baseline check, per-voice phone audits, and the consumer
# smoke over the locally built dist/ tree. BASELINE pins the last
# published release manifest: bundles may only be added or grow.
BASELINE ?= https://github.com/AACTools/voicegarden-lexicons/releases/download/v0.5.1/lexicons.json

check-release:
	cargo test --quiet
	cargo clippy --all-targets -- -D warnings
	python3 scripts/validate_release.py --baseline $(BASELINE)
	python3 scripts/audit_voice_tokens.py
	cargo run --release --quiet --example consumer_smoke

clean:
	rm -rf dist target
