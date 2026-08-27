#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把结构化简历 md 灌进 interactive-resume.html，输出一份可交互的 HTML。

用法：
    python build_resume.py --md polished.md --out resume.html [--template single]

功能：
- 解析 md → 结构化数据
- 从 HTML 模板抽取 52 公司 + 12 学校 logo，遇到匹配名称自动内嵌 <img>
- 内联 jsPDF 与中文字体（按用字子集化），产出单文件自包含 HTML

环境要求：
- Python 3.8+
- fontTools（可选但强烈建议：pip install fonttools）
  缺失时字体无法子集化，会退化为不内联字体，PDF 导出中文会显示异常。
"""
import argparse
import base64
import re
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_HTML = SKILL_ROOT / 'templates' / 'interactive-resume.html'
VENDOR_DIR = SKILL_ROOT / 'vendor'
DEFAULT_TEMPLATE_ID = 'single'
TEMPLATE_IDS = {'single', 'double', 'tech', 'minimal', 'block', 'corner', 'bilingual'}


# ---------- 从 HTML 抽 logo ----------
def load_logo_map(html_text):
    """返回 { '公司名/学校名': dataURI } 映射（用于插入到经历前）"""
    logos = {}
    for arr in ['COMPANY_LOGOS', 'SCHOOL_LOGOS']:
        m = re.search(rf'const {arr} = \[(.*?)\];', html_text, re.S)
        if not m:
            continue
        for name, svg in re.findall(r"\{ name: '([^']+)', svg: '([^']+)' \}", m.group(1)):
            data_uri = 'data:image/svg+xml;base64,' + base64.b64encode(
                svg.encode('utf-8')).decode('ascii')
            logos[name] = data_uri
    return logos


def find_logo(name, logo_map):
    """公司/学校名 → logo dataURI。宽松匹配（去空格、大小写不敏感）"""
    if not name:
        return None
    key = name.strip()
    if key in logo_map:
        return logo_map[key]
    # 宽松匹配：清理空格/横线/括号后再比
    norm = re.sub(r'[\s\-（）()]', '', key).lower()
    for k, v in logo_map.items():
        if re.sub(r'[\s\-（）()]', '', k).lower() == norm:
            return v
    # 部分匹配（key 包含或被包含）
    for k, v in logo_map.items():
        if k in key or key in k:
            return v
    return None


# ---------- md 解析 ----------
def parse_md(md_text):
    """解析结构化简历 md，返回 dict。

    支持字段：name, objective, basic{}, education[], experience[], projects[], skills[], summary[]
    每个经历条目 = {title_left, title_right, bullets[]}
    """
    data = {
        'name': '',
        'objective': '',
        'basic': {},
        'education': [],
        'experience': [],
        'projects': [],
        'skills': [],
        'summary': [],
    }
    section = None
    cur_item = None

    section_map = {
        '基本信息': 'basic',
        '教育经历': 'education', '教育背景': 'education',
        '实习经历': 'experience', '工作经历': 'experience',
        '实习/工作经历': 'experience', '实习 / 工作经历': 'experience',
        '项目经历': 'projects', '项目': 'projects',
        '技能': 'skills', '核心技能': 'skills',
        '自我评价': 'summary', '个人评价': 'summary', '个人描述': 'summary',
    }

    def flush():
        nonlocal cur_item
        if cur_item is None:
            return
        if section in ('education', 'experience', 'projects'):
            data[section].append(cur_item)
        cur_item = None

    for raw in md_text.split('\n'):
        line = raw.rstrip()
        if not line.strip():
            continue

        # H1: 姓名 + 求职意向
        if line.startswith('# '):
            flush()
            head = line[2:].strip()
            # 兼容 "李明的简历"、"李明简历" 这类冗余写法
            head = re.sub(r'(的)?简历$', '', head).strip()
            if '·' in head or '|' in head:
                parts = re.split(r'\s*[·|]\s*', head, maxsplit=1)
                data['name'] = parts[0].strip()
                if len(parts) > 1:
                    obj = parts[1].strip()
                    obj = re.sub(r'^求职意向[：:]\s*', '', obj)
                    data['objective'] = obj
            else:
                data['name'] = head
            section = None
            continue

        # H2: 板块
        if line.startswith('## '):
            flush()
            section = section_map.get(line[3:].strip())
            continue

        # H4: 项目标题（一段实习下可以有多个项目）
        # 渲染成蓝色加粗的 .project-title，后续 bullet 归属该项目
        if line.startswith('#### '):
            if cur_item is not None:
                cur_item['blocks'].append({
                    'type': 'project',
                    'text': line[5:].strip(),
                })
            continue

        # H3: 经历条目
        if line.startswith('### '):
            flush()
            fields = [f.strip() for f in line[4:].split('|')]
            cur_item = {
                'title_left': ' · '.join(fields[:-1]) if len(fields) > 1 else fields[0],
                'title_right': fields[-1] if len(fields) > 1 else '',
                'blocks': [],
            }
            continue

        # bullet
        if line.startswith('- ') or line.startswith('* '):
            content = line[2:].strip()
            if section == 'basic':
                m = re.match(r'^([^：:]+)[：:](.*)$', content)
                if m:
                    data['basic'][m.group(1).strip()] = m.group(2).strip()
            elif section in ('skills', 'summary'):
                data[section].append(content)
            elif section in ('education', 'experience', 'projects') and cur_item is not None:
                cur_item['blocks'].append({'type': 'bullet', 'text': content})
            continue

        # 整行加粗且形如「**项目：xxx**」的，也视为项目标题（兼容旧写法）
        if line.startswith('**') and cur_item is not None:
            stripped = line.strip()
            if stripped.endswith('**') and re.match(r'^\*\*项目[：:]', stripped):
                cur_item['blocks'].append({
                    'type': 'project',
                    'text': re.sub(r'^\*\*项目[：:]\s*|\*\*$', '', stripped).strip(),
                })
            else:
                cur_item['blocks'].append({'type': 'bullet', 'text': line})

    flush()
    return data


# ---------- 渲染 HTML ----------
def html_escape(s):
    return (s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            .replace('"', '&quot;'))


def render_bullet(text):
    """把 bullet 里的 **加粗** 转成 <strong>，其他保留"""
    esc = html_escape(text)
    esc = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', esc)
    return esc


def render_entry(entry, logo_map):
    """渲染一个经历条目（教育/实习/项目通用）

    结构：.company（公司/学校 + 时间）之后，按 md 顺序交替渲染
    .project-title（蓝色项目名）与 <ul>（bullet 组）。
    """
    left = entry['title_left']
    right = entry['title_right']
    # 从 left 里提取第一段作为潜在公司/学校名（用于 logo 匹配）
    first_seg = re.split(r'\s*[·|]\s*', left, maxsplit=1)[0].strip()
    logo = find_logo(first_seg, logo_map)
    logo_img = f'<img class="company-logo" src="{logo}" alt="logo">' if logo else ''

    # 按顺序把 blocks 折叠成 HTML：连续 bullet 合并进一个 <ul>
    body_parts = []
    pending = []

    def flush_bullets():
        if pending:
            lis = ''.join(f'<li>{render_bullet(t)}</li>' for t in pending)
            body_parts.append(f'<ul>{lis}</ul>')
            pending.clear()

    for blk in entry.get('blocks', []):
        if blk['type'] == 'project':
            flush_bullets()
            # 项目名与项目类型之间的 | 用浅色分隔条包裹，视觉上形成层次
            title_html = render_bullet(blk['text'])
            title_html = re.sub(
                r'\s*\|\s*', '<span class="sep-bar">|</span>', title_html, count=1)
            body_parts.append(f'<div class="project-title">{title_html}</div>')
        else:
            pending.append(blk['text'])
    flush_bullets()

    return f'''<div class="company">
      <div class="company-name">{logo_img}{html_escape(left)}</div>
      <div class="company-role">{html_escape(right)}</div>
    </div>
    {''.join(body_parts)}'''


def render_section(title, entries_html, section_field):
    return f'''<section class="section" data-field="{section_field}">
      <h2 class="section-title">{title}</h2>
      {entries_html}
    </section>'''


def render_flat_section(title, items, section_field):
    """技能/自我评价这类扁平列表"""
    if not items:
        return ''
    lis = ''.join(f'<li>{render_bullet(x)}</li>' for x in items)
    return f'''<section class="section" data-field="{section_field}">
      <h2 class="section-title">{title}</h2>
      <ul>{lis}</ul>
    </section>'''


# 占位值识别：整体形如「待…补充/待填/暂无/TBD/xxx/---」等无信息量文本。
# 用宽松匹配，覆盖「待补充」「待用户补充」「待用户提供」「暂未提供」这类变体。
PLACEHOLDER_PAT = re.compile(
    r'^('
    r'待[\u4e00-\u9fa5]{0,4}(补充|填写|填|确认|提供|定)'
    r'|暂[未无][\u4e00-\u9fa5]{0,4}'
    r'|暂无|无|未知|不详'
    r'|TBD|TODO|N/?A|NULL|NONE'
    r'|x{2,}|\?{1,}|-{1,}|_{2,}|\.{3,}'
    r')[。.!！]?$', re.I)


def is_placeholder(v):
    """判断字段值是否为占位垃圾（不应渲染进最终简历）"""
    if not v:
        return True
    s = str(v).strip().strip('\u3000')   # 同时去掉全角空格
    return not s or bool(PLACEHOLDER_PAT.match(s))


def clean_field(v):
    """占位值归一化为空串"""
    return '' if is_placeholder(v) else str(v).strip()


def build_header_html(data, template_id):
    """按模板生成对应的 header 结构。

    tech（无照片项目型）的 header 是「姓名 + 联系方式 + 多行 meta + 一句话定位」
    的信息密集布局，不放照片；其余模板用「左侧信息 + 右上照片」的通用结构。
    缺失或占位（待补充/TBD/XXX 等）的字段一律不渲染，避免占位垃圾进入简历。
    """
    b = data['basic']
    objective = clean_field(data['objective'] or b.get('求职意向', ''))
    name = clean_field(data['name'] or b.get('姓名', '')) or '姓名'
    contact_parts = [clean_field(b.get(k, '')) for k in ['电话', '邮箱', '城市', '出生年月']]
    contact = '　|　'.join(x for x in contact_parts if x)

    if template_id == 'tech':
        # meta 行：把求职意向与可选的补充信息合并成一行强调文字
        meta_bits = [x for x in [objective, clean_field(b.get('毕业年份', '')),
                                 clean_field(b.get('年龄', ''))] if x]
        meta = ' · '.join(meta_bits)
        links = (clean_field(b.get('链接', '')) or clean_field(b.get('GitHub', ''))
                 or clean_field(b.get('个人主页', '')))
        # edu-line：取第一段教育经历压成一行摘要
        edu_line = ''
        if data['education']:
            e0 = data['education'][0]
            edu_line = f"{e0['title_left']} · {e0['title_right']}".strip(' ·')
        summary_line = b.get('一句话定位', '') or b.get('定位', '')

        rows = [f'<h1 data-field="name">{html_escape(name)}</h1>']
        if contact:
            rows.append(f'<div class="contact" data-field="contact">{html_escape(contact)}</div>')
        if meta:
            rows.append(f'<div class="meta" data-field="meta"><strong>{html_escape(meta)}</strong></div>')
        if links:
            rows.append(f'<div class="meta" data-field="links">{html_escape(links)}</div>')
        if edu_line:
            rows.append(f'<div class="meta" data-field="edu-line">{html_escape(edu_line)}</div>')
        header = ('<header class="resume-head">\n      '
                  + '\n      '.join(rows)
                  + '\n      <div class="photo" data-field="photo" contenteditable="false"'
                    ' title="点击上传照片" style="display:none;">照片</div>\n    </header>')
        if summary_line:
            header += (f'\n    <div class="summary-line" data-field="summary-line">'
                       f'{html_escape(summary_line)}</div>')
        return header

    return f'''<header class="resume-head">
      <div class="head-main">
        <h1 data-field="name">{html_escape(name)}</h1>
        <div class="objective" data-field="objective">{html_escape('求职意向：' + objective) if objective else ''}</div>
        <div class="contact" data-field="contact">{html_escape(contact)}</div>
      </div>
      <div class="photo" data-field="photo" contenteditable="false" title="点击上传照片">照片</div>
    </header>'''


def build_sheet_html(data, logo_map, template_id):
    """组装 <div id="sheet"> 的 innerHTML 内容"""
    edu_html = ''.join(render_entry(e, logo_map) for e in data['education'])
    exp_html = ''.join(render_entry(e, logo_map) for e in data['experience'])
    proj_html = ''.join(render_entry(e, logo_map) for e in data['projects'])

    edu_sec = render_section('教育经历', edu_html, 'education') if edu_html else ''
    exp_sec = render_section('实习 / 工作经历', exp_html, 'experience') if exp_html else ''
    proj_sec = render_section('项目经历', proj_html, 'projects') if proj_html else ''
    skill_sec = render_flat_section('核心技能', data['skills'], 'skills')
    sum_sec = render_flat_section('自我评价', data['summary'], 'summary')

    # 左右双栏：左窄栏放照片 + 姓名 + 联系方式 + 教育 + 技能，右宽栏放经历
    if template_id == 'double':
        b = data['basic']
        objective = clean_field(data['objective'] or b.get('求职意向', ''))
        name = clean_field(data['name'] or b.get('姓名', '')) or '姓名'
        contact_parts = [clean_field(b.get(k, '')) for k in ['电话', '邮箱', '城市', '出生年月']]
        contact = '<br>'.join(html_escape(x) for x in contact_parts if x)
        return f'''<div class="two-col">
      <aside class="col-left">
        <div class="photo" data-field="photo" contenteditable="false" title="点击上传照片">照片</div>
        <h1 data-field="name">{html_escape(name)}</h1>
        <div class="contact" data-field="contact">{contact}</div>
        {edu_sec}
        {skill_sec}
      </aside>
      <div class="col-right">
        <div class="objective" data-field="objective">{html_escape('求职意向：' + objective) if objective else ''}</div>
        {exp_sec}
        {proj_sec}
        {sum_sec}
      </div>
    </div>'''

    header = build_header_html(data, template_id)
    sections = [s for s in [edu_sec, exp_sec, proj_sec, skill_sec, sum_sec] if s]
    return header + '\n' + '\n'.join(sections)


# ---------- 注入模板 ----------
# PDF 可用字体。key 与 HTML 端 PDF_FAMILY 的键一致。
# 思源黑体对应「微软雅黑 / 黑体」，思源宋体对应「宋体 / 楷体」。
# 楷体没有可自由分发的开源等价字体，用宋体近似（衬线族，比黑体更接近）。
#
# 字体文件不随 skill 分发（4 个文件共 40MB+），首次运行时按需下载到 vendor/ 缓存。
# 均为 SIL OFL 1.1 授权，可自由使用与再分发。
FONT_SOURCES = {
    'font.ttf': 'https://cdn.jsdelivr.net/gh/adobe-fonts/source-han-sans@release/SubsetOTF/CN/SourceHanSansCN-Regular.otf',
    'font-bold.ttf': 'https://cdn.jsdelivr.net/gh/adobe-fonts/source-han-sans@release/SubsetOTF/CN/SourceHanSansCN-Bold.otf',
    'serif.otf': 'https://cdn.jsdelivr.net/gh/adobe-fonts/source-han-serif@release/SubsetOTF/CN/SourceHanSerifCN-Regular.otf',
    'serif-bold.otf': 'https://cdn.jsdelivr.net/gh/adobe-fonts/source-han-serif@release/SubsetOTF/CN/SourceHanSerifCN-Bold.otf',
}

PDF_FONTS = {
    'sans': ('font.ttf', 'font-bold.ttf'),      # 思源黑体
    'serif': ('serif.otf', 'serif-bold.otf'),   # 思源宋体
}


def ensure_asset(filename, url=None):
    """返回 vendor 下的资源路径；本地不存在时从 CDN 下载并缓存。

    字体与 jsPDF 共 40MB+，不随 skill 分发，首次运行时按需下载。
    """
    path = VENDOR_DIR / filename
    if path.exists() and path.stat().st_size > 1024:
        return path

    url = url or FONT_SOURCES.get(filename)
    if not url:
        raise FileNotFoundError(f'缺少资源 {filename}，且没有配置下载源')

    import urllib.request
    VENDOR_DIR.mkdir(parents=True, exist_ok=True)
    print(f'  首次运行，下载 {filename} …')
    tmp = path.with_suffix(path.suffix + '.part')
    try:
        with urllib.request.urlopen(url, timeout=180) as resp, open(tmp, 'wb') as f:
            f.write(resp.read())
        tmp.replace(path)
    except Exception as exc:
        if tmp.exists():
            tmp.unlink()
        raise RuntimeError(
            f'{filename} 下载失败：{exc}\n'
            f'可手动下载后放到 {VENDOR_DIR}/：\n  {url}'
        ) from exc
    return path


def subset_font(font_path, chars):
    """把字体裁剪为只含 chars 里的字符，返回 TrueType(glyf) bytes。

    完整 CJK 字体约 10MB，base64 内联后 HTML 会膨胀到 20MB+。
    一份简历实际只用几百个字，子集化后通常 < 300KB。

    思源宋体是 OTF/CFF 轮廓，jsPDF 内部的 fontkit 对 CFF 支持不稳定，
    需转成 glyf 轮廓（见 _cff_to_glyf）。
    fontTools 不可用时回退为原字体。
    """
    try:
        from fontTools import subset
    except ImportError:
        return Path(font_path).read_bytes()

    import io
    options = subset.Options()
    options.layout_features = ['*']
    options.notdef_outline = True
    options.recalc_bounds = True
    font = subset.load_font(str(font_path), options)
    subsetter = subset.Subsetter(options=options)
    subsetter.populate(text=''.join(sorted(chars)))
    subsetter.subset(font)

    if 'CFF ' in font:
        font = _cff_to_glyf(font)

    # 两套字体统一裁掉排版特性表与竖排表：
    # PDF 是逐字定位绘制，不使用 OpenType 特性；保留它们只会增大体积，
    # 且黑体/宋体表结构不一致时 fontkit 行为可能有差异。
    for tag in ['GSUB', 'GPOS', 'BASE', 'VORG', 'vhea', 'vmtx', 'GDEF', 'kern']:
        if tag in font:
            del font[tag]

    buf = io.BytesIO()
    font.save(buf)
    return buf.getvalue()


def _cff_to_glyf(font):
    """CFF（三次贝塞尔）轮廓转 glyf（二次贝塞尔），供 jsPDF/fontkit 使用。

    关键点：CFF 字体没有 glyf 轮廓专属的 loca 表，只建 glyf 不建 loca 会让
    fontkit 解析字形时读到 undefined（表现为 glyphFor 崩溃）。必须让 fontTools
    重新编译一遍，由它自动生成 loca 并校正 maxp/hmtx 等派生数据。
    """
    import io
    from fontTools.ttLib import TTFont, newTable
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    from fontTools.pens.cu2quPen import Cu2QuPen

    glyph_set = font.getGlyphSet()
    order = font.getGlyphOrder()

    glyf = newTable('glyf')
    glyf.glyphs = {}
    glyf.glyphOrder = order
    for name in order:
        pen = TTGlyphPen(glyph_set)
        glyph_set[name].draw(Cu2QuPen(pen, 1.0))
        glyf.glyphs[name] = pen.glyph()
    font['glyf'] = glyf
    for name in order:
        glyf.glyphs[name].recalcBounds(glyf)

    # loca 必须存在，编译时由 fontTools 依据 glyf 生成
    font['loca'] = newTable('loca')

    # 移除 CFF 专属与竖排相关表：fontkit 对它们的组合较敏感，
    # 简历排版也不需要竖排/基线扩展
    for tag in ['CFF ', 'VORG', 'BASE', 'vhea', 'vmtx', 'GSUB', 'GPOS']:
        if tag in font:
            del font[tag]

    font['head'].indexToLocFormat = 0

    # maxp 从 CFF 的 0.5 版升到 TrueType 的 1.0 版，补齐专属字段
    maxp = font['maxp']
    maxp.tableVersion = 0x00010000
    defaults = dict(maxZones=2, maxTwilightPoints=0, maxStorage=0, maxFunctionDefs=0,
                    maxInstructionDefs=0, maxStackElements=0, maxSizeOfInstructions=0,
                    maxComponentElements=0, maxComponentDepth=0, maxPoints=0,
                    maxContours=0, maxCompositePoints=0, maxCompositeContours=0)
    for key, val in defaults.items():
        if not hasattr(maxp, key):
            setattr(maxp, key, val)

    # 走一遍完整的 save/load，让 fontTools 生成 loca 并校正所有派生数据，
    # 得到结构上与原生 TTF 一致的字体
    buf = io.BytesIO()
    font.save(buf)
    buf.seek(0)
    return TTFont(buf)


def inject(html_text, sheet_content, template_id, content_key):
    # 1) 改 data-template
    html_text = re.sub(
        r'(id="sheet"[^>]*data-template=")[^"]*(")',
        rf'\1{template_id}\2', html_text
    )
    # 2) 替换 contentKey，让每份简历有独立的 localStorage 存储空间，
    #    避免多份简历互相覆盖上次编辑
    html_text = re.sub(
        r"const contentKey = '[^']*';",
        f"const contentKey = '{content_key}';",
        html_text, count=1
    )
    # 3) 内联 jsPDF：产物 HTML 用 file:// 打开时，外部 <script src> 与 fetch()
    #    都会受同源策略限制，必须把依赖全部内联，做成单文件自包含
    jspdf_code = ensure_asset(
        'jspdf.umd.min.js',
        'https://cdn.jsdelivr.net/npm/jspdf@2.5.1/dist/jspdf.umd.min.js'
    ).read_text(encoding='utf-8')
    html_text = re.sub(
        r'<script src="\.\./vendor/jspdf\.umd\.min\.js"></script>',
        lambda _: '<script>' + jspdf_code + '</script>',
        html_text, count=1
    )
    # 4) 内联 CJK 字体（base64），替换掉基于 fetch 的 loadFont 实现。
    #    file:// 下 fetch 本地文件会被 CORS 拦截报 "Failed to fetch"。
    #    字体先按简历实际用字子集化，避免 HTML 膨胀到 20MB+。
    #    黑体与宋体两套都内联，PDF 渲染时按元素实际 font-family 选用，
    #    保证「网页上选什么字体，导出 PDF 就是什么字体」。
    used_chars = set(re.sub(r'<[^>]+>', '', sheet_content))
    used_chars |= set(
        '0123456789'
        'abcdefghijklmnopqrstuvwxyz'
        'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
        # PDF 渲染时由代码直接输出、可能不在正文里的字符
        '\u2022\u25cf\u25aa\u00b7'
        # 常用标点与符号（含全角）
        ' \u3000·—–-/|\\、，。：；！？（）()《》〈〉「」【】'
        '%+&*#@.,:;\'"“”‘’…~^_=<>[]{}'
        # 常见箭头与数学符号（简历里常出现 → ≈ ≥ 等）
        '→←↑↓⇒≈≥≤±×÷°'
        # 货币与单位
        '$￥€£'
    )

    font_consts = []
    for key, (reg_file, bold_file) in PDF_FONTS.items():
        reg = base64.b64encode(
            subset_font(ensure_asset(reg_file), used_chars)).decode('ascii')
        bold = base64.b64encode(
            subset_font(ensure_asset(bold_file), used_chars)).decode('ascii')
        font_consts.append(f"'{key}': {{ normal: '{reg}', bold: '{bold}' }}")

    inline_fonts = (
        'const PDF_FONT_B64 = {\n          '
        + ',\n          '.join(font_consts)
        + '\n        };\n'
        + "        const loadFont = async (family, bold) => "
          "((PDF_FONT_B64[family] || PDF_FONT_B64.sans)[bold ? 'bold' : 'normal']);"
    )
    html_text = re.sub(
        r'const loadFont = async \(url\) => \{.*?\n        \};',
        lambda _: inline_fonts,
        html_text, count=1, flags=re.S
    )
    # 5) 替换 <main class="sheet"...> 的内容
    pattern = r'(<main class="sheet"[^>]*id="sheet"[^>]*>)(.*?)(</main>)'
    def replace(m):
        return m.group(1) + '\n' + sheet_content + '\n  ' + m.group(3)
    return re.sub(pattern, replace, html_text, count=1, flags=re.S)


# ---------- main ----------
def main():
    ap = argparse.ArgumentParser(description='把 md 灌进 interactive-resume.html')
    ap.add_argument('--md', required=True, help='润色后的结构化简历 md 路径')
    ap.add_argument('--out', required=True, help='输出 HTML 路径')
    ap.add_argument('--template', default=DEFAULT_TEMPLATE_ID,
                    choices=sorted(TEMPLATE_IDS),
                    help=f'简历样式模板 ID（默认 {DEFAULT_TEMPLATE_ID}）')
    args = ap.parse_args()

    md_text = Path(args.md).read_text(encoding='utf-8')
    html_text = TEMPLATE_HTML.read_text(encoding='utf-8')
    logo_map = load_logo_map(html_text)

    data = parse_md(md_text)
    sheet = build_sheet_html(data, logo_map, args.template)

    # 为每份简历生成独立 contentKey。
    # 把 sheet 内容也纳入哈希：内容一变 key 就变，重新生成后不会被上一版的
    # localStorage 缓存覆盖（否则用户看到的仍是旧内容）。
    import hashlib
    final_name = data['name'] or data['basic'].get('姓名', 'resume')
    final_obj = data['objective'] or data['basic'].get('求职意向', '')
    key_seed = f'{final_name}|{final_obj}|{Path(args.out).resolve()}|{sheet}'
    content_key = 'resume-' + hashlib.md5(key_seed.encode('utf-8')).hexdigest()[:12]

    result = inject(html_text, sheet, args.template, content_key)

    out_path = Path(args.out)
    out_path.write_text(result, encoding='utf-8')

    # 报告 logo 命中情况
    hit, miss = [], []
    for section in ['education', 'experience', 'projects']:
        for e in data[section]:
            first = re.split(r'\s*[·|]\s*', e['title_left'], maxsplit=1)[0].strip()
            (hit if find_logo(first, logo_map) else miss).append(first)

    print(f'✓ 生成 {args.out}')
    print(f'  模板：{args.template}')
    print(f'  姓名：{final_name} / 意向：{final_obj}')
    print(f'  存储 key：{content_key}')
    print(f'  经历数：教育 {len(data["education"])} 实习 {len(data["experience"])} 项目 {len(data["projects"])}')
    print(f'  Logo 命中：{len(hit)}/{len(hit)+len(miss)}')
    if miss:
        print(f'  未命中（用户可在 HTML 里手动补 logo）：{", ".join(sorted(set(miss)))}')


if __name__ == '__main__':
    main()
