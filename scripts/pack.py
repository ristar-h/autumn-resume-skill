#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把本 skill 打包成可上传的 zip。

用法：
    python scripts/pack.py [--out ~/Downloads]

会剔除以下内容，保证包体远小于 3MB 上限：
- vendor/ 下的字体与 jsPDF（运行时按需下载，无需分发）
- .git / __pycache__ / .DS_Store 等本地产物

文件名以 UTF-8 标记写入，Windows 解压中文目录名不会乱码。
"""
import argparse
import shutil
import tempfile
import zipfile
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
SKILL_NAME = SKILL_ROOT.name
SIZE_LIMIT = 3 * 1024 * 1024   # Skill 包上限 3MB

# 不进包的文件名模式
EXCLUDE_SUFFIX = {'.ttf', '.otf', '.part', '.pyc'}
EXCLUDE_NAMES = {'.DS_Store', 'jspdf.umd.min.js'}
EXCLUDE_DIRS = {'.git', '__pycache__', 'node_modules'}


def should_skip(path, root):
    rel = path.relative_to(root)
    if any(part in EXCLUDE_DIRS for part in rel.parts):
        return True
    if path.name in EXCLUDE_NAMES:
        return True
    if path.suffix.lower() in EXCLUDE_SUFFIX:
        return True
    return False


def main():
    ap = argparse.ArgumentParser(description='打包 skill 为 zip')
    ap.add_argument('--out', default=str(Path.home() / 'Downloads'),
                    help='输出目录（默认 ~/Downloads）')
    args = ap.parse_args()

    out_dir = Path(args.out).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f'{SKILL_NAME}.zip'

    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / SKILL_NAME
        shutil.copytree(
            SKILL_ROOT, staging,
            ignore=lambda d, names: [
                n for n in names
                if n in EXCLUDE_DIRS or n in EXCLUDE_NAMES
                or Path(n).suffix.lower() in EXCLUDE_SUFFIX
            ]
        )

        files = []
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED,
                             compresslevel=9) as z:
            for p in sorted(staging.rglob('*')):
                if should_skip(p, staging.parent):
                    continue
                info = zipfile.ZipInfo.from_file(p, p.relative_to(tmp).as_posix())
                info.flag_bits |= 0x800          # 文件名按 UTF-8 标记
                info.compress_type = zipfile.ZIP_DEFLATED
                if p.is_dir():
                    info.filename += '/'
                    z.writestr(info, b'')
                else:
                    z.writestr(info, p.read_bytes())
                    files.append((p.relative_to(staging).as_posix(),
                                  p.stat().st_size))

    size = zip_path.stat().st_size
    print(f'✓ {zip_path}')
    print(f'  包体：{size / 1024:.0f} KB（上限 {SIZE_LIMIT // 1024 // 1024} MB）')
    print(f'  文件：{len(files)} 个，解压后 {sum(s for _, s in files) / 1024:.0f} KB')
    print()
    for name, s in files:
        print(f'  {s:>8}  {name}')

    if size > SIZE_LIMIT:
        print()
        print(f'✗ 超出上限 {(size - SIZE_LIMIT) / 1024:.0f} KB，请检查是否有大文件混入')
        raise SystemExit(1)


if __name__ == '__main__':
    main()
