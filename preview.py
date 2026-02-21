from dataclasses import dataclass

TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".log",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".html",
    ".css",
    ".scss",
    ".sh",
    ".sql",
    ".xml",
    ".csv",
    ".dat",
    ".go",
    ".rs",
    ".java",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".f90",
}

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}


@dataclass
class DecodedText:
    text: str
    encoding: str


def looks_like_text(sample: bytes) -> bool:
    if not sample:
        return True
    if b"\x00" in sample:
        # UTF-16 often has many nulls; allow it if pattern matches.
        even_null = sum(1 for i in range(0, len(sample), 2) if sample[i] == 0)
        odd_null = sum(1 for i in range(1, len(sample), 2) if sample[i] == 0)
        if max(even_null, odd_null) < len(sample) * 0.15:
            return False
    printable = 0
    for b in sample:
        if b in (9, 10, 13) or 32 <= b <= 126:
            printable += 1
    return (printable / len(sample)) >= 0.70


def decode_bytes(data: bytes) -> DecodedText:
    if not data:
        return DecodedText("", "utf-8")

    # BOM-guided decode first.
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        try:
            return DecodedText(data.decode("utf-16"), "utf-16")
        except UnicodeDecodeError:
            pass

    for enc in ("utf-8", "utf-16"):
        try:
            text = data.decode(enc)
            if enc == "utf-16" and "\x00" in text:
                continue
            return DecodedText(text, enc)
        except UnicodeDecodeError:
            continue

    return DecodedText(data.decode("latin-1", errors="replace"), "latin-1")


def should_preview_as_image(ext: str, size: int, image_limit: int) -> bool:
    return ext in IMAGE_EXTENSIONS and size <= image_limit


def should_preview_as_text(ext: str, sample: bytes) -> bool:
    return ext in TEXT_EXTENSIONS or looks_like_text(sample)
