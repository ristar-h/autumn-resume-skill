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


# SKILL.md frontmatter 必填字段
REQUIRED_FIELDS = ['name', 'version', 'display_name', 'display_name_en',
                   'description', 'description_zh', 'description_en']


def check_frontmatter():
    """打包前预检 SKILL.md 的 frontmatter，避免打出无法上传的包。

    重点检查裸标量里的「冒号+空格」——YAML 会把它当成新的键值对，
    报 "mapping values are not allowed in this context"。长描述一律用引号包裹。
    """
    import re
    text = (SKILL_ROOT / 'SKILL.md').read_text(encoding='utf-8')
    m = re.match(r'^---\r?\n(.*?)\r?\n---', text, re.S)
    if not m:
        return ['SKILL.md 缺少 frontmatter（--- 包裹的头部）']

    problems, seen = [], {}
    for i, line in enumerate(m.group(1).split('\n'), 1):
        if not line.strip():
            continue
        if line[0] in ' \t':
            problems.append(f'frontmatter 第 {i} 行以空白开头，会被当作续行')
            continue
        if ':' not in line:
            problems.append(f'frontmatter 第 {i} 行缺少冒号')
            continue
        key, val = line.split(':', 1)
        key, val = key.strip(), val.strip()
        seen[key] = val
        quoted = (len(val) >= 2 and val[0] == val[-1] and val[0] in '"\'')
        if not quoted and ': ' in val:
            problems.append(
                f'{key} 的值含「冒号+空格」但未加引号，YAML 会解析失败')
        if val.startswith('"') != val.endswith('"'):
            problems.append(f'{key} 的双引号不配对')

    for field in REQUIRED_FIELDS:
        if not seen.get(field):
            problems.append(f'缺少必填字段 {field}')

    return problems


def main():
    ap = argparse.ArgumentParser(description='打包 skill 为 zip')
    ap.add_argument('--out', default=str(Path.home() / 'Downloads'),
                    help='输出目录（默认 ~/Downloads）')
    ap.add_argument('--skip-check', action='store_true',
                    help='跳过 frontmatter 预检')
    args = ap.parse_args()

    if not args.skip_check:
        issues = check_frontmatter()
        if issues:
            print('✗ SKILL.md frontmatter 预检未通过：')
            for it in issues:
                print(f'  - {it}')
            raise SystemExit(1)
        print('✓ frontmatter 预检通过')

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
