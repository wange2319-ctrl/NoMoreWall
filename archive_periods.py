#!/usr/bin/env python3
"""Roll generated subscriptions and retain only current + previous periods."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path

PERIODS = Path("periods")
CURRENT = PERIODS / "current"
PREVIOUS = PERIODS / "previous"
FILES = [
    "list.best.meta.yml",
    "list.best.yml",
    "list.best.txt",
    "list.meta.yml",
    "list.yml",
    "list.txt",
    "list_raw.txt",
    "list_result.csv",
    "list_best_report.csv",
]
SNIPPET_FILES = [
    "snippets/nodes.best.meta.yml",
    "snippets/nodes.best.yml",
]


def assert_safe_dir(path: Path) -> None:
    base = PERIODS.resolve()
    target = path.resolve()
    if target.parent != base:
        raise RuntimeError(f"拒绝操作 periods 之外的目录：{target}")


def remove_tree(path: Path) -> None:
    assert_safe_dir(path)
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def rotate() -> None:
    PERIODS.mkdir(exist_ok=True)
    if PREVIOUS.exists():
        remove_tree(PREVIOUS)
    if CURRENT.exists():
        CURRENT.rename(PREVIOUS)
        print(f"上一期已轮换到 {PREVIOUS}")
    else:
        print("当前没有可轮换的订阅期。")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot() -> None:
    PERIODS.mkdir(exist_ok=True)
    if CURRENT.exists():
        remove_tree(CURRENT)
    CURRENT.mkdir(parents=True)

    copied: list[str] = []
    for name in FILES:
        source = Path(name)
        if not source.exists():
            if name in {"list.best.meta.yml", "list.best.yml", "list.best.txt"}:
                raise FileNotFoundError(f"缺少精选订阅文件：{name}")
            continue
        destination = CURRENT / source.name
        shutil.copy2(source, destination)
        copied.append(destination.relative_to(CURRENT).as_posix())

    for name in SNIPPET_FILES:
        source = Path(name)
        if source.exists():
            destination = CURRENT / source.name
            shutil.copy2(source, destination)
            copied.append(destination.relative_to(CURRENT).as_posix())

    metadata = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "retention": "current_and_previous_only",
        "files": {
            name: {
                "size": (CURRENT / name).stat().st_size,
                "sha256": sha256(CURRENT / name),
            }
            for name in copied
        },
    }
    (CURRENT / "period.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    allowed = {"current", "previous", "README.md"}
    for item in PERIODS.iterdir():
        if item.name not in allowed:
            if item.is_dir():
                assert_safe_dir(item)
                shutil.rmtree(item)
            else:
                item.unlink()
            print(f"已清除过期内容：{item}")
    print(f"本期快照已写入 {CURRENT}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["rotate", "snapshot"])
    args = parser.parse_args()
    if args.action == "rotate":
        rotate()
    else:
        snapshot()


if __name__ == "__main__":
    main()
