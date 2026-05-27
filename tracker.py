#!/usr/bin/env python3
"""
TapTap 游戏在线人数追踪器
每小时抓取一次，保存 CSV，生成可视化 HTML

用法:
  python tracker.py              # 抓取一次 + 生成 HTML
  python tracker.py --html-only  # 仅从 CSV 生成 HTML

定时运行 (Linux cron):
  0 * * * * cd /path/to/project && python tracker.py

定时运行 (Windows 任务计划):
  schtasks /create /tn TapTapTracker /tr "python tracker.py" /sc hourly
"""

import os, sys, io, json, csv, time, hmac, hashlib, base64, random, string
import urllib.parse, requests
from pathlib import Path
from datetime import datetime, timedelta

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ============================================================
# 配置
# ============================================================
SCRIPT_DIR = Path(__file__).parent
CSV_FILE = SCRIPT_DIR / "online_history.csv"
HTML_FILE = SCRIPT_DIR / "online_chart.html"
LOG_FILE = SCRIPT_DIR / "tracker.log"
GAME_INFO_FILE = SCRIPT_DIR / "game_info.json"

KID = os.environ.get('TAPTAP_KID', '')
MAC_KEY = os.environ.get('TAPTAP_MAC_KEY', '')
API_HOST = 'api.taptapdada.com'
X_UA = 'V=1&PN=TapPC&VN=2026.5.19-rel.5&VN_CODE=2026051905&CH=organic-direct_index_d20260425--260425ayD0RBcx9pod&OS=windows&OSV=10.0.26200&LANG=zh_CN&UID=2802356a81894c5dae8768bc07c5e29d&SR=1920x1080&VID=658693348'
X_UA_ENC = urllib.parse.quote(X_UA, safe='')

REQUEST_DELAY = 0.8  # 每个请求间隔，避免限流

# 日志
def log(msg):
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{now}] {msg}'
    print(line, flush=True)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(line + '\n')

GAMES = [
    ('异环', '714119'),
    ('火炬之光：无限', '172664'),
    ('洛克王国：世界', '188212'),
    ('鸣潮', '234280'),
    ('心动小镇', '45213'),
    ('原神', '168332'),
    ('超自然行动组', '714123'),
    ('明日方舟：终末地', '232326'),
    ('和平精英', '70056'),
    ('三角洲行动', '330259'),
    ('伊瑟', '236627'),
    ('明日方舟', '70253'),
    ('崩坏：星穹铁道', '224267'),
    ('燕云十六声', '239372'),
    ('绝区零', '234493'),
    ('幻塔', '192675'),
]

# ============================================================
# API 请求
# ============================================================

# 模式: 'direct' (MAC签名直连) 或 'pipe' (Windows 命名管道)
API_MODE = 'direct'

def api_req_direct(full_path):
    """直连 API (MAC 签名)"""
    ts = str(int(time.time()))
    nonce = ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(8))
    p = urllib.parse.urlparse(full_path)
    ru = p.path
    if p.query:
        ru += '?' + p.query
    norm = f'{ts}\n{nonce}\nGET\n{ru}\n{API_HOST}\n443\n\n'
    sig = base64.b64encode(hmac.new(MAC_KEY.encode(), norm.encode(), hashlib.sha1).digest()).decode()
    headers = {
        'Host': API_HOST, 'Accept': 'application/json',
        'User-Agent': 'TapTap/2026.5.19-rel.5 (Build 2026051905/1d8a57a6) TapPC-Main/2026.5.19-rel.5',
        'Authorization': f'MAC id="{KID}",ts="{ts}",nonce="{nonce}",mac="{sig}"',
    }
    return requests.get(f'https://{API_HOST}{full_path}', headers=headers, timeout=15)


PIPE_PATH = '\\\\.\\pipe\\tappc_cn_http'

def pipe_exists():
    try:
        fd = os.open(PIPE_PATH, os.O_RDWR | os.O_BINARY)
        os.close(fd)
        return True
    except:
        return False

def api_req_pipe(full_path):
    """Pipe 请求 (自动认证)"""
    fd = os.open(PIPE_PATH, os.O_RDWR | os.O_BINARY)
    req = f'GET {full_path}&X-UA={X_UA_ENC} HTTP/1.1\r\nHost: {API_HOST}\r\nAccept: application/json\r\nUser-Agent: TapTap/2026.5.19-rel.5\r\nX-TAPPC-PROXY: taptap\r\nConnection: close\r\n\r\n'
    os.write(fd, req.encode())
    resp = b''
    while True:
        try:
            c = os.read(fd, 8192)
            if not c:
                break
            resp += c
        except BlockingIOError:
            time.sleep(0.05)
        except:
            break
    os.close(fd)
    if b'\r\n\r\n' not in resp:
        return None
    hdr, body = resp.split(b'\r\n\r\n', 1)
    if b'chunked' in hdr:
        d = b''
        while body:
            e = body.find(b'\r\n')
            if e < 0:
                break
            sz = int(body[:e], 16)
            if sz == 0:
                break
            d += body[e+2:e+2+sz]
            body = body[e+2+sz+2:]
        body = d

    class PipeResponse:
        def __init__(self, b):
            self.content = b
            self.status_code = 200 if b and b[:1] == b'{' else 400
        def json(self):
            return __import__('json').loads(self.content)
    return PipeResponse(body)


def api_req(full_path):
    if API_MODE == 'pipe':
        return api_req_pipe(full_path)
    return api_req_direct(full_path)


def count_online(game_id):
    """精确计数（翻页到底）"""
    current_path = f'/group/v1/online-players?app_id={game_id}&from=0&limit=50'
    total = 0
    page = 0
    while current_path and page < 500:
        page += 1
        resp = api_req(current_path)
        if not resp or resp.status_code != 200:
            if page == 1:
                log(f'    第1页失败 (HTTP {resp.status_code if resp else "no response"})')
                return None
            log(f'    第{page}页中断')
            break
        data = resp.json()
        lst = data.get('data', {}).get('list', [])
        next_url = data.get('data', {}).get('next_page', '')
        if not lst:
            break
        total += len(lst)
        if not next_url:
            break
        next_path = next_url.replace(f'https://{API_HOST}', '')
        current_path = f'{next_path}'
        time.sleep(REQUEST_DELAY)
        if page % 30 == 0 or page == 1:
            log(f'    第{page}页: +{len(lst)} = {total} 累计')
    return total


# ============================================================
# 游戏信息缓存
# ============================================================

WEB_X_UA = 'V=1&PN=WebApp&LANG=zh_CN&VN_CODE=102&LOC=CN&PLT=PC&DS=Android&UID=d52ddf3e-6028-4fa4-ba5a-56d8a7bb4729&OS=Windows&OSV=10&DT=PC'

def fetch_game_info(game_id):
    """获取游戏详情 (评分/粉丝/下载等)"""
    params = {'id': game_id, 'Identifier': f'auto_{game_id}', 'X-UA': WEB_X_UA}
    headers = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}
    resp = requests.get(f'https://{API_HOST}/app/v3/detail', params=params, headers=headers, timeout=15)
    if resp.status_code != 200:
        return None
    app = resp.json().get('data', {}).get('app', {})
    stat = app.get('stat', {})
    devs = app.get('developers', [])
    rating = stat.get('rating', {})
    return {
        'title': app.get('title', ''),
        'identifier': app.get('identifier', ''),
        'update_date': app.get('update_date', ''),
        'score': rating.get('score', ''),
        'latest_version_score': rating.get('latest_version_score', ''),
        'latest_score': rating.get('latest_score', ''),
        'latest_review_count': rating.get('latest_review_count', 0),
        'fans_count': stat.get('fans_count', 0),
        'review_count': stat.get('review_count', 0),
        'pc_download_count': stat.get('pc_download_count', 0),
        'tags': [t.get('value', '') for t in app.get('tags', [])],
        'developer': devs[0].get('name', '') if devs else '',
        'icon_url': app.get('icon', {}).get('medium_url', ''),
    }


def load_game_info():
    """加载游戏信息缓存"""
    if GAME_INFO_FILE.exists():
        with open(GAME_INFO_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_game_info(info):
    with open(GAME_INFO_FILE, 'w', encoding='utf-8') as f:
        json.dump(info, f, ensure_ascii=False, indent=2)


def ensure_game_info():
    """刷新所有游戏基本信息（每次运行都更新）"""
    info = load_game_info()
    updated = False
    for gname, gid in GAMES:
        log(f'  更新游戏信息: {gname} (ID={gid})')
        gi = fetch_game_info(gid)
        if gi:
            info[gid] = gi
            updated = True
            time.sleep(0.5)
    if updated:
        save_game_info(info)
    log(f'  已更新 {len(info)} 款游戏信息')
    return info


# ============================================================
# CSV 操作
# ============================================================

def load_csv():
    """读取历史数据"""
    if not CSV_FILE.exists():
        return []
    rows = []
    with open(CSV_FILE, 'r', encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def append_csv(timestamp, counts):
    """追加或更新本小时数据（取最大值）"""
    # timestamp 格式: '2026-05-27 14:00' (精确到小时)
    hour_key = timestamp[:13]  # '2026-05-27 14'
    fieldnames = ['time'] + [g[0] for g in GAMES]

    # 读取现有数据
    rows = []
    updated = False
    if CSV_FILE.exists() and CSV_FILE.stat().st_size > 0:
        with open(CSV_FILE, 'r', encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row['time'][:13] == hour_key:
                    # 同一小时：取最大值
                    for gname in [g[0] for g in GAMES]:
                        old_val = int(row[gname]) if row[gname] and row[gname].strip() else 0
                        new_val = counts.get(gname, 0) or 0
                        row[gname] = max(old_val, new_val)
                    updated = True
                rows.append(row)

    if not updated:
        # 新的一小时：追加
        row = {'time': timestamp}
        for gname in [g[0] for g in GAMES]:
            row[gname] = counts.get(gname, '')
        rows.append(row)

    # 写回
    with open(CSV_FILE, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# ============================================================
# HTML 图表生成
# ============================================================

def generate_html():
    """从 CSV 生成可视化 HTML — 标签页切换各游戏"""
    rows = load_csv()
    game_info = load_game_info()
    if not rows:
        log("CSV 为空，无法生成图表")
        return

    game_names = [g[0] for g in GAMES]
    timestamps = []
    series = {name: [] for name in game_names}

    for row in rows:
        timestamps.append(row['time'])
        for name in game_names:
            val = row.get(name, '')
            series[name].append(int(val) if val and val.strip() else None)

    active_games = []
    for name in game_names:
        vals = [v for v in series[name] if v is not None and v > 0]
        if vals:
            active_games.append(name)

    colors = [
        '#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0', '#9966FF',
        '#FF9F40', '#7CB342', '#E91E63', '#00BCD4', '#FF5722',
        '#9C27B0', '#3F51B5', '#009688', '#F44336', '#607D8B', '#CDDC39'
    ]

    # 最新数据 + 上期数据
    latest = {name: series[name][-1] for name in active_games}
    prev = {name: series[name][-2] if len(series[name]) > 1 else None for name in active_games}
    top_games = sorted(latest.items(), key=lambda x: x[1] or 0, reverse=True)

    ts_json = json.dumps(timestamps, ensure_ascii=False)
    series_json = {}
    for name in active_games:
        series_json[name] = [v if v is not None else None for v in series[name]]

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TapTap 游戏在线人数追踪</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family: -apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif; background:#1a1a2e; color:#eee; }}
.app {{ display:flex; height:100vh; }}
.sidebar {{ width:200px; background:#0f0f23; padding:12px 0; overflow-y:auto; flex-shrink:0; border-right:1px solid #2a2a4a; }}
.sidebar h3 {{ color:#666; font-size:12px; padding:8px 16px; text-transform:uppercase; letter-spacing:1px; }}
.sidebar button {{ display:block; width:100%; padding:10px 16px; border:none; background:none; color:#aaa; text-align:left; cursor:pointer; font-size:13px; transition:.2s; }}
.sidebar button:hover {{ background:#1a1a3e; color:#fff; }}
.sidebar button.active {{ background:#1a1a3e; color:#fff; border-left:3px solid #36A2EB; font-weight:600; }}
.main {{ flex:1; overflow-y:auto; padding:24px; }}
.main h2 {{ font-size:22px; margin-bottom:4px; }}
.main .meta {{ color:#888; font-size:12px; margin-bottom:20px; }}
.stats {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(140px,1fr)); gap:10px; margin-bottom:20px; }}
.stat-card {{ background:#16213e; border-radius:8px; padding:14px; text-align:center; }}
.stat-card .label {{ font-size:11px; color:#888; }}
.stat-card .value {{ font-size:22px; font-weight:700; margin:4px 0; }}
.stat-card .change {{ font-size:11px; }}
.up {{ color:#4caf50; }}
.down {{ color:#f44336; }}
.flat {{ color:#666; }}
.chart-wrap {{ background:#16213e; border-radius:10px; padding:20px; }}
canvas {{ width:100%; max-height:420px; }}
.page {{ display:none; }}
.page.active {{ display:block; }}
.footer {{ text-align:center; color:#555; font-size:12px; margin-top:24px; }}
</style>
</head>
<body>
<div class="app">
<div class="sidebar">
<h3>游戏列表</h3>
<button class="active" onclick="showPage('overview')">总览</button>
'''

    for i, name in enumerate(top_games):
        gid = name[0] if isinstance(name, tuple) else ''
        html += f'<button onclick="showPage(\'game{i}\')">{gid}</button>\n'

    html += '''</div>
<div class="main">
'''

    # ---- 总览页面 ----
    html += '<div id="page-overview" class="page active">\n'
    html += f'<h2>全部游戏</h2>\n'
    html += f'<p class="meta">数据范围: {timestamps[0]} ~ {timestamps[-1]} | {len(timestamps)} 个数据点</p>\n'

    # 总览卡片
    html += '<div class="stats">\n'
    for gname, count in top_games:
        i = active_games.index(gname)
        change_html = ''
        if count is not None and prev[gname] is not None and prev[gname] > 0:
            pct = (count - prev[gname]) / prev[gname] * 100
            if pct > 1:
                change_html = f'<span class="up">▲{pct:.0f}%</span>'
            elif pct < -1:
                change_html = f'<span class="down">▼{abs(pct):.0f}%</span>'
            else:
                change_html = '<span class="flat">─</span>'
        html += f'''<div class="stat-card" style="cursor:pointer" onclick="showPage('game{i}')">
<div class="label">{gname}</div>
<div class="value">{count or 0:,}</div>
<div class="change">{change_html}</div>
</div>\n'''
    html += '</div>\n'

    # 总览图
    datasets_overview = []
    for i, name in enumerate(active_games):
        vals = series[name]
        datasets_overview.append({
            'label': name, 'data': vals,
            'borderColor': colors[i % len(colors)],
            'backgroundColor': colors[i % len(colors)] + '20',
            'borderWidth': 1.5, 'pointRadius': 1, 'tension': 0.3, 'fill': False,
        })
    html += '<div class="chart-wrap"><canvas id="chartOverview"></canvas></div>\n'
    html += '</div>\n'

    # 总览图 JS
    html += f'''<script>
const timestamps = {ts_json};
const allSeries = {json.dumps(series_json, ensure_ascii=False)};
const allNames = {json.dumps(active_games, ensure_ascii=False)};
const colors = {json.dumps(colors, ensure_ascii=False)};

new Chart(document.getElementById('chartOverview').getContext('2d'), {{
    type: 'line',
    data: {{ labels: timestamps, datasets: {json.dumps(datasets_overview, ensure_ascii=False)} }},
    options: {{
        responsive: true, maintainAspectRatio: false,
        interaction: {{ mode: 'index', intersect: false }},
        plugins: {{ legend: {{ position: 'bottom', labels: {{ color: '#ccc', usePointStyle: true, padding: 12, font: {{ size:11 }} }} }} }},
        scales: {{
            x: {{ ticks: {{ color: '#888', maxTicksLimit: 20, maxRotation: 45 }} }},
            y: {{ ticks: {{ color: '#888', callback: v => v>=1000 ? (v/1000).toFixed(1)+'k' : v }} }}
        }}
    }}
}});
</script>
'''

    # ---- 每个游戏的独立页面 ----
    for i, gname in enumerate(active_games):
        vals = series[gname]
        valid_vals = [v for v in vals if v is not None]
        cur = latest[gname]
        prev_val = prev[gname]
        max_val = max(valid_vals) if valid_vals else 0
        min_val = min(valid_vals) if valid_vals else 0
        avg_val = sum(valid_vals) / len(valid_vals) if valid_vals else 0

        change_html = ''
        if cur is not None and prev_val is not None and prev_val > 0:
            pct = (cur - prev_val) / prev_val * 100
            if pct > 1: change_html = f'<span class="up">▲{pct:.0f}%</span>'
            elif pct < -1: change_html = f'<span class="down">▼{abs(pct):.0f}%</span>'
            else: change_html = '<span class="flat">─</span>'

        color = colors[i % len(colors)]

        html += f'<div id="page-game{i}" class="page">\n'
        html += f'<h2>{gname}</h2>\n'

        # 游戏基础信息
        gid = dict(GAMES).get(gname, '')
        gi = game_info.get(str(gid), {}) if gid else {}
        if gi:
            tags_html = ' '.join(f'<span style="display:inline-block;background:#1a1a3e;padding:2px 8px;border-radius:3px;font-size:11px;margin:2px">{t}</span>' for t in gi.get('tags', [])[:5])
            html += '<div style="display:flex;gap:16px;align-items:flex-start;margin-bottom:16px;background:#16213e;border-radius:8px;padding:16px">\n'
            if gi.get('icon_url'):
                html += f'<img src="{gi["icon_url"]}" style="width:64px;height:64px;border-radius:12px;flex-shrink:0" referrerpolicy="no-referrer" onerror="this.style.display=\'none\'">\n'
            html += '<div style="flex:1">\n'
            html += f'<div style="font-size:13px;color:#aaa;margin-bottom:6px">{tags_html}</div>\n'
            fans_wan = gi.get('fans_count', 0) / 10000
            review_wan = gi.get('review_count', 0) / 10000
            pc_dl_wan = gi.get('pc_download_count', 0) / 10000
            latest_rev_wan = gi.get('latest_review_count', 0) / 10000
            html += '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px 16px;font-size:13px">\n'
            html += f'<div><span style="color:#888;font-size:11px">游戏 ID</span><br><span style="font-size:22px;font-weight:700">{gid}</span></div>\n'
            html += f'<div><span style="color:#888;font-size:11px">游戏名称</span><br><span style="font-size:22px;font-weight:700">{gi.get("title",gname)}</span></div>\n'
            html += f'<div><span style="color:#888;font-size:11px">粉丝数</span><br><span style="font-size:22px;font-weight:700">{fans_wan:.1f}万</span></div>\n'
            html += f'<div><span style="color:#888;font-size:11px">评价总数</span><br><span style="font-size:22px;font-weight:700">{review_wan:.1f}万</span></div>\n'
            html += f'<div><span style="color:#888;font-size:11px">当前评分</span><br><span style="color:#FFCE56;font-size:22px;font-weight:700">{gi.get("score","?")}</span><span style="color:#888"> / 10</span></div>\n'
            html += f'<div><span style="color:#888;font-size:11px">最新版本评分</span><br><span style="font-size:22px;font-weight:700">{gi.get("latest_version_score","?")}</span></div>\n'
            html += f'<div><span style="color:#888;font-size:11px">最近 7 天评分</span><br><span style="font-size:22px;font-weight:700">{gi.get("latest_score","?")}</span><span style="color:#888;font-size:13px"> ({latest_rev_wan:.1f}万评价)</span></div>\n'
            html += f'<div><span style="color:#888;font-size:11px">开发商</span><br><span style="font-size:22px;font-weight:700">{gi.get("developer","?")}</span></div>\n'
            if pc_dl_wan > 0:
                html += f'<div><span style="color:#888;font-size:11px">PC下载</span><br><span style="font-size:22px;font-weight:700">{pc_dl_wan:.1f}万</span></div>\n'
            if gi.get('update_date'):
                html += f'<div><span style="color:#888;font-size:11px">更新日期</span><br><span style="font-size:22px;font-weight:700">{gi["update_date"]}</span></div>\n'
            html += '</div></div></div>\n'

        html += f'<p class="meta">{len(timestamps)} 个数据点 | {timestamps[0]} ~ {timestamps[-1]}</p>\n'

        html += '<div class="stats">\n'
        html += f'<div class="stat-card"><div class="label">当前在线</div><div class="value">{cur or 0:,}</div><div class="change">{change_html}</div></div>\n'
        html += f'<div class="stat-card"><div class="label">最高</div><div class="value">{max_val:,}</div></div>\n'
        html += f'<div class="stat-card"><div class="label">最低</div><div class="value">{min_val:,}</div></div>\n'
        html += f'<div class="stat-card"><div class="label">平均</div><div class="value">{avg_val:,.0f}</div></div>\n'
        html += '</div>\n'

        ds = [{
            'label': gname, 'data': vals,
            'borderColor': color, 'backgroundColor': color + '30',
            'borderWidth': 2, 'pointRadius': 3, 'pointHoverRadius': 5,
            'tension': 0.3, 'fill': True,
        }]
        html += f'<div class="chart-wrap"><canvas id="chartGame{i}"></canvas></div>\n'
        html += f'''<script>
new Chart(document.getElementById('chartGame{i}').getContext('2d'), {{
    type: 'line',
    data: {{ labels: timestamps, datasets: {json.dumps(ds, ensure_ascii=False)} }},
    options: {{
        responsive: true, maintainAspectRatio: false,
        plugins: {{ legend: {{ display: false }} }},
        scales: {{
            x: {{ ticks: {{ color: '#888', maxTicksLimit: 20, maxRotation: 45 }} }},
            y: {{ ticks: {{ color: '#888', callback: v => v>=1000 ? (v/1000).toFixed(1)+'k' : v }} }}
        }}
    }}
}});
</script>
'''
        html += '</div>\n'

    # 切换脚本
    html += f'''</div>
</div>

<script>
function showPage(id) {{
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.sidebar button').forEach(b => b.classList.remove('active'));
    document.getElementById('page-' + id).classList.add('active');
    event.target.classList.add('active');
}}
</script>

<div class="footer" style="position:fixed;bottom:0;left:200px;right:0;text-align:center;padding:8px;background:#0f0f23;">
最后更新: {timestamps[-1]} · 数据来源: api.taptapdada.com · TapTap 在线追踪器
</div>
</body>
</html>'''

    with open(HTML_FILE, 'w', encoding='utf-8') as f:
        f.write(html)
    log(f'HTML 已生成: {HTML_FILE}')


# ============================================================
# 主程序
# ============================================================

def fetch_all():
    """抓取所有游戏在线人数"""
    if API_MODE == 'direct' and (not KID or not MAC_KEY):
        print('错误: 直连模式需要设置 TAPTAP_KID / TAPTAP_MAC_KEY')
        print('或使用 --pipe 模式')
        sys.exit(1)
    if API_MODE == 'pipe' and not pipe_exists():
        print('错误: Pipe 不存在，请先启动 TapTap 客户端')
        sys.exit(1)

    log(f'开始抓取 {len(GAMES)} 款游戏在线人数')
    log(f'模式: {API_MODE} | 间隔: 页{REQUEST_DELAY}s/游戏2s')
    log('-' * 50)

    counts = {}
    success = 0
    fail = 0
    start_time = time.time()

    for i, (gname, gid) in enumerate(GAMES):
        game_start = time.time()
        log(f'[{i+1}/{len(GAMES)}] {gname} (ID={gid}) 查询中...')
        total = count_online(gid)
        elapsed = time.time() - game_start

        if total is not None:
            counts[gname] = total
            success += 1
            log(f'  ✓ {gname}: {total:,} 人 ({elapsed:.1f}s)')
        else:
            counts[gname] = 0
            fail += 1
            log(f'  ✗ {gname}: 获取失败 ({elapsed:.1f}s)')

        # 游戏间延迟
        if i < len(GAMES) - 1:
            time.sleep(2)

    total_time = time.time() - start_time

    # 保存 CSV（精确到小时，同小时内多次运行取最大值）
    now = datetime.now()
    hour_ts = now.strftime('%Y-%m-%d %H:00')
    append_csv(hour_ts, counts)
    csv_rows = len(load_csv())
    log(f'CSV 已保存: {CSV_FILE} (时间点: {hour_ts}, 共 {csv_rows} 行)')

    # 每次运行都刷新游戏基本信息
    log('更新游戏基本信息...')
    ensure_game_info()

    # 生成 HTML
    generate_html()

    log(f'完成! 成功 {success}/{len(GAMES)}, 失败 {fail}, 总耗时 {total_time:.0f}s')


def main():
    global API_MODE
    if '--pipe' in sys.argv:
        API_MODE = 'pipe'
    elif '--direct' in sys.argv:
        API_MODE = 'direct'
    else:
        API_MODE = 'pipe' if pipe_exists() else 'direct'

    if '--html-only' in sys.argv:
        log('仅生成 HTML')
        generate_html()
    else:
        fetch_all()


if __name__ == '__main__':
    main()
