.PHONY: all clean fetcher-test

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

clean:
	rm -rf dist target
