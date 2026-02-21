# Nova SFTP Explorer

Modern SFTP desktop explorer focused on **remote preview without downloading files locally first**.

## Features

- Remote browser with folder navigation (`Go`, `Up`, breadcrumb, back/forward)
- Fast filter/search with optional hidden-file toggle
- Smart preview tabs:
  - Text preview with paging
  - Image preview with fit/zoom/pan controls
  - Hex fallback for binary files
  - Metadata view
- Transfer queue with upload/download progress

## Install

```bash
pip install nova-sftp-explorer
```

## Run

```bash
nova-sftp-explorer
```

## Local development

```bash
pip install -e .
python sftp.py
```

## Publish (maintainer)

```bash
python -m pip install --upgrade build twine
python -m build
python -m twine check dist/*
python -m twine upload dist/*
```

## License

MIT
