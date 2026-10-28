"""Render all contribution dates as one continuous, wrapped calendar."""
import datetime as dt
import html
import json
import math
import xml.etree.ElementTree as ET

COLORS = ['#eff2f5', '#aceebb', '#4ac26b', '#2da44e', '#116329']
THEMES = {
    'light': {'background':'#ffffff','foreground':'#1f2328','muted':'#59636e','border':'#d1d9e0','hover':'#f6f8fa','stroke':'#1f2328','strokeOpacity':'.08','palette':COLORS},
    'dark': {'background':'#0d1117','foreground':'#f0f6fc','muted':'#9198a1','border':'#3d444d','hover':'#151b23','stroke':'#000000','strokeOpacity':'.05','palette':['#151b23','#033a16','#196c2e','#2ea043','#56d364']},
}
WEEKDAYS = ['月', '火', '水', '木', '金', '土', '日']
COLUMNS = 52
STEP = 13
CELL = 10
LEFT = 36
TOP = 64
WIDTH = 800


def esc(value):
    return html.escape(str(value), quote=True)


def cell_position(origin, date, bands):
    week, weekday = divmod((date - origin).days, 7)
    band, column = divmod(week, COLUMNS)
    band = bands - 1 - band
    return LEFT + column * STEP, TOP + (band * 7 + weekday) * STEP


def text(x, y, value, size=12, color='#59636e', weight=400, extra=''):
    return f'<text x="{x}" y="{y}" fill="{color}" font-size="{size}" font-weight="{weight}" {extra}>{esc(value)}</text>'


def svg_theme_styles():
    rules = []
    for name,colors in THEMES.items():
        selector = f'svg[data-theme="{name}"]'
        rules.extend([
            f'{selector} .canvas{{fill:{colors["background"]}}}',
            f'{selector} text{{fill:{colors["muted"]}}}',
            f'{selector} text.primary{{fill:{colors["foreground"]}}}',
            f'{selector} .day,{selector} .shade{{stroke:{colors["stroke"]};stroke-opacity:{colors["strokeOpacity"]}}}',
        ])
        for level,color in enumerate(colors['palette']):
            rules.append(f'{selector} .day[data-level="{level}"],{selector} .shade[data-level="{level}"]{{fill:{color}}}')
    return ''.join(rules)


def calendar_svg(report, interactive=False, theme='light'):
    colors = THEMES[theme]
    palette = colors['palette']
    meta = report['metadata']
    start = dt.date.fromisoformat(meta['periodStart'])
    end = dt.date.fromisoformat(meta['periodEnd'])
    origin = start - dt.timedelta(days=(start.weekday() + 1) % 7)
    weeks = (end - origin).days // 7 + 1
    bands = math.ceil(weeks / COLUMNS)
    grid_height = bands * 7 * STEP
    height = TOP + grid_height + 29
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" viewBox="0 0 {WIDTH} {height}" class="calendar" role="img" aria-labelledby="map-title" data-layout="continuous" data-week-columns="{COLUMNS}" data-band-order="newest-first" data-theme="{theme}"><title id="map-title">{esc(meta["user"])} {meta["periodStart"]} — {meta["periodEnd"]}</title><style>text{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif}}{svg_theme_styles()}.calendar .day:hover,.calendar .day:focus{{outline:none;stroke:#0969da;stroke-width:1.5;stroke-opacity:1}}</style><rect class="canvas" width="{WIDTH}" height="{height}" fill="{colors["background"]}"/>']
    parts.append(text(LEFT,25,meta['user'],19,colors['foreground'],600,extra='class="primary"'))
    parts.append(text(WIDTH-17,25,f'{report["summary"]["total"]:,} contributions',13,colors['foreground'],extra='text-anchor="end" class="primary"'))
    parts.append(text(LEFT,45,meta['periodStart']+' — '+meta['periodEnd'],11,colors['muted']))
    parts.append(text(WIDTH-17,45,f'{report["summary"]["activeDays"]:,} days',11,colors['muted'],extra='text-anchor="end" data-stat="active-days"'))
    for band in range(bands):
        for label, row in [('Mon',1),('Wed',3),('Fri',5)]:
            parts.append(text(LEFT+COLUMNS*STEP+19,TOP+(band*7+row)*STEP+8,label,9,colors['muted'],extra=f'data-weekday="{label}"'))
    parts.append('<g id="contribution-grid">')
    for day in report['days']:
        date = dt.date.fromisoformat(day['date'])
        x, y = cell_position(origin,date,bands)
        label = f'{day["date"]}（{WEEKDAYS[date.weekday()]}） · {day["count"]:,} contributions'
        attrs = f' data-date="{day["date"]}" data-count="{day["count"]}" data-level="{day["level"]}"'
        if interactive:
            attrs += f' tabindex="0" role="button" aria-label="{esc(label)}"'
        parts.append(f'<rect class="day" x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="2" fill="{palette[day["level"]]}" stroke="{colors["stroke"]}" stroke-opacity="{colors["strokeOpacity"]}"{attrs}><title>{esc(label)}</title></rect>')
    parts.append('</g><g id="year-labels">')
    for year in range(end.year,start.year-1,-1):
        first = max(start,dt.date(year,1,1))
        band = bands - 1 - ((first-origin).days//7)//COLUMNS
        y = TOP + band*7*STEP + 3*STEP + CELL/2 + 4
        parts.append(text(2,y,year,13,colors['muted'],500,extra=f'data-year="{year}"'))
    parts.append('</g>')
    legend_y = TOP + grid_height + 12
    parts.append(text(LEFT+COLUMNS*STEP-151,legend_y+8,'Less',10,colors['muted']))
    for level,color in enumerate(palette):
        parts.append(f'<rect class="shade" data-level="{level}" x="{LEFT+COLUMNS*STEP-120+level*STEP}" y="{legend_y}" width="10" height="10" rx="2" fill="{color}" stroke="{colors["stroke"]}" stroke-opacity="{colors["strokeOpacity"]}"/>')
    parts.append(text(LEFT+COLUMNS*STEP-49,legend_y+8,'More',10,colors['muted']))
    parts.append('</svg>')
    return ''.join(parts)


def render_svg(report, theme='light'):
    return calendar_svg(report,theme=theme)


def render_preview_svg(report, theme='light', max_height=600, fade_height=150):
    """Clip the full calendar without moving cells, fading its last 150px."""
    if max_height<2 or fade_height<1:
        raise ValueError('Preview height must be at least 2px and fade height positive')
    namespace='http://www.w3.org/2000/svg'
    ET.register_namespace('',namespace)
    tag=lambda name:'{'+namespace+'}'+name
    root=ET.fromstring(render_svg(report,theme))
    full_height=int(root.attrib['height'])
    height=min(max_height,full_height)
    root.set('height',str(height))
    root.set('viewBox',f'0 0 {WIDTH} {height}')
    root.set('overflow','hidden')
    root.set('data-preview-height',str(height))
    if full_height>height:
        start=max(0,height-fade_height)
        root.set('data-fade-start',str(start))
        definitions=ET.SubElement(root,tag('defs'))
        gradient=ET.SubElement(definitions,tag('linearGradient'),{
            'id':'preview-gradient','gradientUnits':'userSpaceOnUse',
            'x1':'0','y1':str(start),'x2':'0','y2':str(height-1),
        })
        ET.SubElement(gradient,tag('stop'),{'offset':'0','stop-color':'#ffffff'})
        ET.SubElement(gradient,tag('stop'),{'offset':'1','stop-color':'#000000'})
        mask=ET.SubElement(definitions,tag('mask'),{
            'id':'preview-mask','maskUnits':'userSpaceOnUse','maskContentUnits':'userSpaceOnUse',
            'x':'0','y':'0','width':str(WIDTH),'height':str(height),'mask-type':'luminance',
        })
        ET.SubElement(mask,tag('rect'),{'width':str(WIDTH),'height':str(height),'fill':'url(#preview-gradient)'})
        visible=ET.Element(tag('g'),{'mask':'url(#preview-mask)'})
        for child in list(root):
            if child.tag not in [tag('title'),tag('style'),tag('defs')]:
                root.remove(child)
                visible.append(child)
        root.append(visible)
    return ET.tostring(root,encoding='unicode')


CSS = '''
:root{color-scheme:light}*{box-sizing:border-box}body{margin:0;background:#fff;color:#1f2328;font:13px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif}.shell{max-width:832px;margin:0 auto;padding:14px 16px 22px}.controls{display:flex;align-items:center;justify-content:flex-end;gap:8px;flex-wrap:wrap;margin-bottom:8px}.controls output{margin-right:auto;font-variant-numeric:tabular-nums;color:#59636e}button,input{font:inherit;color:inherit;border:1px solid #d1d9e0;background:#fff;border-radius:5px;padding:4px 7px}button{cursor:pointer}button:hover{background:#f6f8fa}button:focus-visible,input:focus-visible{outline:2px solid #0969da;outline-offset:2px}.calendar{display:block;width:100%;min-width:0;height:auto}.day{cursor:pointer}.calendar .day.selected{stroke:#0969da;stroke-width:1.7;stroke-opacity:1}.tooltip{position:fixed;z-index:10;background:#24292f;color:white;padding:7px 10px;border-radius:5px;font-size:12px;pointer-events:none;white-space:nowrap;box-shadow:0 2px 8px #0002}.tooltip[hidden]{display:none}@media(max-width:520px){.shell{padding:10px 7px}.controls{gap:5px;font-size:11px}input{max-width:132px}.controls output{flex-basis:100%}}@media print{.controls,.tooltip{display:none}.shell{padding:0;max-width:none}.calendar{break-inside:avoid}}
'''
CSS = CSS.replace(':root{color-scheme:light}', ':root{color-scheme:light;--bg:#fff;--fg:#1f2328;--muted:#59636e;--border:#d1d9e0;--hover:#f6f8fa}html[data-theme="dark"]{color-scheme:dark;--bg:#0d1117;--fg:#f0f6fc;--muted:#9198a1;--border:#3d444d;--hover:#151b23}')
for old,new in [('background:#fff','background:var(--bg)'),('color:#1f2328','color:var(--fg)'),('color:#59636e','color:var(--muted)'),('1px solid #d1d9e0','1px solid var(--border)'),('background:#f6f8fa','background:var(--hover)')]:
    CSS = CSS.replace(old,new)

JS = r'''
const REPORT=JSON.parse(document.getElementById('report-data').textContent);
const DAYS=REPORT.days,BYDATE=new Map(DAYS.map(d=>[d.date,d]));
const tip=document.getElementById('tooltip');
const fmt=n=>n.toLocaleString('ja-JP');
const wd=date=>['日','月','火','水','木','金','土'][new Date(date+'T00:00:00Z').getUTCDay()];
let selected=null;
function selectDate(date,scroll=false){
 const d=BYDATE.get(date);if(!d)return;
 if(selected)selected.classList.remove('selected');
 selected=document.querySelector(`rect.day[data-date="${date}"]`);
 if(selected)selected.classList.add('selected');
 document.getElementById('pick-date').value=date;
 document.getElementById('selected-date').textContent=`${date}（${wd(date)}）`;
 document.getElementById('selected-count').textContent=fmt(d.count);
 if(scroll&&selected)selected.scrollIntoView({behavior:'smooth',block:'center',inline:'nearest'});
}
function showTip(el,event){
 const d=BYDATE.get(el.dataset.date);if(!d)return;
 tip.textContent=`${d.date}（${wd(d.date)}） · ${fmt(d.count)} contributions`;
 tip.hidden=false;
 const rect=el.getBoundingClientRect(),x=event?.clientX??rect.left,y=event?.clientY??rect.top;
 tip.style.left=Math.max(6,Math.min(innerWidth-tip.offsetWidth-6,x+12))+'px';
 tip.style.top=Math.max(6,Math.min(innerHeight-tip.offsetHeight-6,y-tip.offsetHeight-10))+'px';
}
document.addEventListener('pointerover',e=>{const el=e.target.closest?.('rect.day');if(el)showTip(el,e)});
document.addEventListener('pointermove',e=>{const el=e.target.closest?.('rect.day');if(el)showTip(el,e)});
document.addEventListener('pointerout',e=>{if(e.target.closest?.('rect.day'))tip.hidden=true});
document.addEventListener('focusin',e=>{if(e.target.matches('rect.day'))showTip(e.target)});
document.addEventListener('focusout',()=>{tip.hidden=true});
document.addEventListener('click',e=>{const el=e.target.closest?.('rect.day');if(el)selectDate(el.dataset.date)});
document.addEventListener('keydown',e=>{if(e.target.matches('rect.day')&&(e.key==='Enter'||e.key===' ')){e.preventDefault();selectDate(e.target.dataset.date)}});
document.getElementById('pick-date').addEventListener('change',e=>selectDate(e.target.value,true));
function download(name,content,type){const url=URL.createObjectURL(new Blob([content],{type}));const a=document.createElement('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000)}
document.getElementById('download-csv').addEventListener('click',()=>{let csv='date,weekday,count,level,before_account_created\n';for(const d of DAYS)csv+=`${d.date},${wd(d.date)},${d.count},${d.level},${d.date<REPORT.metadata.accountCreatedAt.slice(0,10)}\n`;download(REPORT.metadata.user+'-daily.csv',csv,'text/csv;charset=utf-8')});
document.getElementById('download-json').addEventListener('click',()=>download(REPORT.metadata.user+'-contributions.json',JSON.stringify(REPORT,null,2),'application/json;charset=utf-8'));
document.getElementById('toggle-theme').addEventListener('click',()=>{
 const theme=document.documentElement.dataset.theme==='dark'?'light':'dark';
 document.documentElement.dataset.theme=theme;
 document.querySelector('svg.calendar').dataset.theme=theme;
 document.getElementById('toggle-theme').textContent=theme==='dark'?'Light':'Dark';
});
selectDate(REPORT.metadata.periodEnd);
'''


def render_html(report, theme='light'):
    meta = report['metadata']
    user = esc(meta['user'])
    data = json.dumps(report,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c')
    return f'''<!doctype html>
<html lang="ja" data-theme="{theme}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{user} · Contributions</title><style>{CSS}</style></head><body><main class="shell"><div class="controls"><output aria-live="polite"><span id="selected-date">{meta['periodEnd']}</span> · <span id="selected-count">{report['days'][-1]['count']}</span> contributions</output><input aria-label="日付" id="pick-date" type="date" min="{meta['periodStart']}" max="{meta['periodEnd']}" value="{meta['periodEnd']}"><button id="toggle-theme" aria-label="テーマ切り替え">{'Light' if theme=='dark' else 'Dark'}</button><button id="download-csv">CSV</button><button id="download-json">JSON</button></div>{calendar_svg(report,True,theme)}</main><div class="tooltip" id="tooltip" role="tooltip" hidden></div><script type="application/json" id="report-data">{data}</script><script>{JS}</script></body></html>'''
