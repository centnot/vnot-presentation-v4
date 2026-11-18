"""Текст выступления в PDF и DOCX из speech.txt.

Запуск из любой папки: python knd/scripts/speech_docs.py
Нужны python-docx и Playwright с Chromium. Пересобирать после каждого обновления speech.txt.
"""
import html
import re
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor
from playwright.sync_api import sync_playwright

KND = Path(__file__).resolve().parent.parent
SRC = KND / 'speech.txt'
NAVY = '#001657'
GREY = '#5a6478'


def typo(text):
    """Неразрывные пробелы: после коротких слов, между числом и словом, перед тире."""
    nbsp = lambda m: m.group(1) + '\u00a0'
    text = re.sub(r'(?<![\w-])([А-Яа-яЁё]{1,2}) ', nbsp, text)
    text = re.sub(r'(\d) (?=[\w«])', nbsp, text)
    return text.replace(' —', '\u00a0—')


def parse():
    """Возвращает (шапка из трёх строк, вступление, разделы [(заголовок, показ, [абзацы])])."""
    lines = SRC.read_text(encoding='utf-8-sig').splitlines()
    head, rest = lines[:3], lines[3:]
    intro, sections, cur = [], [], None
    for raw in rest:
        line = raw.strip()
        if not line or re.fullmatch(r'-{5,}', line):
            continue
        if re.match(r'^\d+\. ', line) or line == 'ЗАКЛЮЧЕНИЕ':
            cur = [line[0] + line[1:].lower() if line == 'ЗАКЛЮЧЕНИЕ' else line, '', []]
            sections.append(cur)
        elif line.startswith('ПОКАЗ:') and cur is not None:
            cur[1] = line[len('ПОКАЗ:'):].strip()
        elif cur is None:
            intro.append(typo(line))
        else:
            cur[2].append(typo(line))
    return head, intro, sections


def build_pdf(head, intro, sections):
    e = html.escape
    body = [f'<header><p class="org">{e(head[1])}</p><h1>{e(head[0])}</h1><p class="kind">{e(head[2])}</p></header>']
    body += [f'<p>{e(p)}</p>' for p in intro]
    for title, cue, paras in sections:
        block = f'<h2>{e(title)}</h2>'
        if cue:
            block += f'<p class="cue">Показ: {e(cue)}</p>'
        body.append(f'<section><div class="keep">{block}{"<p>" + e(paras[0]) + "</p>" if paras else ""}</div>'
                    + ''.join(f'<p>{e(p)}</p>' for p in paras[1:]) + '</section>')
    doc = f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>{e(head[0])} — {e(head[2].lower())}</title><style>
      @page {{ size: A4; margin: 20mm 20mm 22mm 25mm; }}
      body {{ font-family: Arial, sans-serif; font-size: 13pt; line-height: 1.5; color: #111; }}
      header {{ border-bottom: 2px solid {NAVY}; margin-bottom: 18pt; padding-bottom: 10pt; }}
      .org, .kind {{ margin: 0; color: {GREY}; font-size: 11pt; }}
      h1 {{ margin: 4pt 0; color: {NAVY}; font-size: 20pt; line-height: 1.25; }}
      h2 {{ margin: 22pt 0 4pt; color: {NAVY}; font-size: 15pt; }}
      p {{ margin: 0 0 8pt; }}
      .cue {{ color: {GREY}; font-size: 10.5pt; font-style: italic; line-height: 1.35; }}
      .keep {{ break-inside: avoid; }}
    </style></head><body>{"".join(body)}</body></html>'''
    footer = ('<div style="width:100%;font:9pt Arial,sans-serif;color:#5a6478;padding:0 20mm 0 25mm;'
              'display:flex;justify-content:space-between"><span>' + e(head[0]) + '</span>'
              '<span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>')
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.set_content(doc, wait_until='load')
        pg.pdf(path=str(KND / 'speech.pdf'), format='A4', print_background=True, display_header_footer=True,
               header_template='<span></span>', footer_template=footer,
               margin={'top': '20mm', 'bottom': '22mm', 'left': '25mm', 'right': '20mm'})
        b.close()


def page_field(paragraph):
    run = paragraph.add_run()
    for tag, text in (('begin', None), (None, 'PAGE'), ('end', None)):
        if tag:
            el = OxmlElement('w:fldChar'); el.set(qn('w:fldCharType'), tag)
        else:
            el = OxmlElement('w:instrText'); el.set(qn('xml:space'), 'preserve'); el.text = text
        run._r.append(el)


def build_docx(head, intro, sections):
    d = Document()
    sec = d.sections[0]
    sec.page_width, sec.page_height = Mm(210), Mm(297)
    sec.top_margin, sec.bottom_margin, sec.left_margin, sec.right_margin = Mm(20), Mm(22), Mm(25), Mm(20)
    navy, grey = RGBColor(0x00, 0x16, 0x57), RGBColor(0x5A, 0x64, 0x78)

    normal = d.styles['Normal']
    normal.font.name, normal.font.size = 'Arial', Pt(13)
    rpr = normal.element.get_or_add_rPr()
    fonts = rpr.find(qn('w:rFonts'))
    for attr in ('w:ascii', 'w:hAnsi', 'w:cs', 'w:eastAsia'):
        fonts.set(qn(attr), 'Arial')
    lang = OxmlElement('w:lang'); lang.set(qn('w:val'), 'ru-RU'); rpr.append(lang)
    normal.paragraph_format.line_spacing = 1.5
    normal.paragraph_format.space_after = Pt(6)

    h = d.styles['Heading 1']
    h.font.name, h.font.size, h.font.bold, h.font.color.rgb = 'Arial', Pt(15), True, navy
    hf = h.element.get_or_add_rPr().get_or_add_rFonts()  # в шаблоне заголовок берёт шрифт темы — заменить на Arial
    for attr in list(hf.attrib):
        if attr.endswith('Theme') or attr.endswith('theme'):
            del hf.attrib[attr]
    for attr in ('w:ascii', 'w:hAnsi', 'w:cs', 'w:eastAsia'):
        hf.set(qn(attr), 'Arial')
    h.paragraph_format.space_before, h.paragraph_format.space_after = Pt(18), Pt(4)
    h.paragraph_format.keep_with_next = True

    def small(text, italic=False, size=11, color=grey, keep=False):
        p = d.add_paragraph()
        r = p.add_run(text); r.italic = italic; r.font.size = Pt(size); r.font.color.rgb = color
        p.paragraph_format.line_spacing = 1.2
        p.paragraph_format.keep_with_next = keep
        return p

    small(head[1], keep=True).paragraph_format.space_after = Pt(0)
    t = d.add_paragraph(); r = t.add_run(head[0]); r.bold = True; r.font.size = Pt(20); r.font.color.rgb = navy
    t.paragraph_format.line_spacing = 1.2; t.paragraph_format.space_after = Pt(2)
    small(head[2]).paragraph_format.space_after = Pt(14)

    def body(text):
        d.add_paragraph(text)

    for para in intro:
        body(para)
    for title, cue, paras in sections:
        d.add_heading(title, level=1)
        if cue:
            small('Показ: ' + cue, italic=True, size=10.5, keep=True)
        for para in paras:
            body(para)

    fp = sec.footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    page_field(fp)
    for run in fp.runs:
        run.font.size, run.font.color.rgb = Pt(9), grey
    d.core_properties.title = head[0] + ' — ' + head[2].lower()
    d.core_properties.author = head[1]
    d.save(str(KND / 'speech.docx'))


if __name__ == '__main__':
    parts = parse()
    build_pdf(*parts)
    build_docx(*parts)
    print('speech.pdf, speech.docx:', len(parts[2]), 'разделов')
