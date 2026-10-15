demo:
	cd api && python demo.py

demo-build:
	cd api && python demo.py --build-only

test:
	python -m pytest

web:
	cd web && npm install && npm run build

samples:
	python demo/generator.py --out demo/statements --end 2026-10-14

.PHONY: demo demo-build test web samples
