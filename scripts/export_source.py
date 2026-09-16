"""Export an allowlisted source snapshot without Git history or runtime data."""

import argparse
import hashlib
from pathlib import Path
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
TOP_LEVEL = {".gitignore", ".env.example", "README.md", "requirements.txt", "requirements-dev.txt", "config.py", "main.py", "LICENSE", "THIRD_PARTY_NOTICES.md"}
EXTENSIONS = {
    "core": {".py"}, "scripts": {".py", ".sh"}, "service": {".service"},
    "static": {".html", ".js", ".css", ".woff", ".woff2"},
    "tests": {".py", ".cjs"}, "defaults": {".json"}, ".github/workflows": {".yml", ".yaml"},
}


def source_files(root=PROJECT):
    root = Path(root).resolve()
    candidates = [root / name for name in TOP_LEVEL]
    for directory, extensions in EXTENSIONS.items():
        candidates.extend(path for path in (root / directory).rglob("*") if path.suffix in extensions)
    result = []
    for path in candidates:
        if not path.is_file() or path.is_symlink() or "__pycache__" in path.parts:
            continue
        if not path.resolve().is_relative_to(root):
            raise ValueError(f"源码路径越出项目目录：{path.name}")
        result.append(path)
    return sorted(set(result))


def export_source(output, root=PROJECT):
    root, output = Path(root).resolve(), Path(output).resolve()
    files = source_files(root)
    if output.exists():
        raise ValueError("输出文件已存在，请选择新的文件名")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            entry = zipfile.ZipInfo("xray-web/" + path.relative_to(root).as_posix(), date_time=(2026, 1, 1, 0, 0, 0))
            entry.external_attr = (0o100755 if path.suffix == ".sh" else 0o100644) << 16
            archive.writestr(entry, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED)
    return len(files), hashlib.sha256(output.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        count, digest = export_source(args.output)
    except (ValueError, OSError) as exc:
        parser.exit(1, str(exc) + "\n")
    print(f"已导出 {count} 个源码文件：{args.output}\nSHA256 {digest}")


if __name__ == "__main__":
    main()
