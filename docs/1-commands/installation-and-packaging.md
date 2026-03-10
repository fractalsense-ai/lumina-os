# installation-and-packaging

Installation and packaging workflows for Project Lumina.

## Requirements files workflow (pip)

Runtime dependencies:

```bash
pip install -r requirements.txt
```

Runtime + development dependencies:

```bash
pip install -r requirements-dev.txt
```

## One-liner developer setup (uv)

```bash
uv venv && uv pip install -r requirements-dev.txt
```

## Editable install (pyproject)

Use editable install when you want command entrypoints and local package iteration.

```bash
# pip
python -m pip install -e .

# or uv
uv pip install -e .
```

## CLI entrypoints

After editable install:

```bash
lumina-api
lumina-verify
lumina-orchestrator-demo
lumina-ctl-validate
lumina-yaml-convert
```

## Backward compatibility

Existing script-based commands remain valid:

```bash
python reference-implementations/lumina-api-server.py
python reference-implementations/verify-repo-integrity.py
```
