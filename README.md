# Nova SFTP Explorer

A modern, cross-platform SFTP desktop explorer focused on **remote-first file inspection**.

**Current version:** `0.1.5`

## Screenshot

![Nova SFTP Explorer main window](https://raw.githubusercontent.com/tanmoy456/nova-sftp-explorer/main/assets/screenshots/nova-sftp-explorer-main.png)

## Why Nova SFTP Explorer

Most SFTP clients are optimized for transfers. Nova is optimized for fast remote inspection:

- Browse remote directories quickly
- Preview text/images/metadata without full local downloads
- Search/filter large directory listings
- Move through folder history with back/forward navigation

## Key Features

- **Connection & navigation**
  - Host/port/user/password login via SFTP
  - `Go`, `Up`, `Back`, `Forward`, breadcrumbs
  - Hidden file toggle and live filter

- **Preview-first workflow**
  - Text preview with paging for large files
  - Smart text decoding (`utf-8`, `utf-16`, fallback `latin-1`)
  - Image preview with fit/zoom/pan controls
  - Hex preview fallback for binary files
  - Metadata tab (path, size, permissions, modified)

- **Transfers**
  - Upload/download with progress queue
  - Transfer status tracking in-app

- **Persistence**
  - Saved connection profiles
  - UI preferences (splitter, column widths, last profile)
  - Per-user state file location on macOS/Linux/Windows

## Installation

```bash
pip install nova-sftp-explorer
```

## Run

```bash
nova-sftp-explorer
```

## Upgrade

```bash
python3 -m pip install -U nova-sftp-explorer
```

## Platform Notes

- Python `>=3.10`
- Linux users may need Tk runtime:

```bash
sudo apt install -y python3-tk
```

## Development

```bash
git clone https://github.com/tanmoy456/nova-sftp-explorer.git
cd nova-sftp-explorer
python -m pip install -e .
python sftp.py
```

## Testing

```bash
python -m unittest tests/test_preview.py
```

## Release (maintainer)

```bash
python -m pip install --upgrade build twine
rm -rf dist build *.egg-info
python -m build
python -m twine check dist/*
python -m twine upload dist/*
```

## Roadmap

- SSH key auth + known_hosts verification
- Inline text edit and save-back-to-remote
- Enhanced conflict handling on remote file changes

## License

MIT
