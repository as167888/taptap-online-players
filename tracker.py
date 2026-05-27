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
    """追加一行数据"""
    file_exists = CSV_FILE.exists()
    with open(CSV_FILE, 'a', encoding='utf-8', newline='') as f:
        fieldnames = ['time'] + [g[0] for g in GAMES]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists or CSV_FILE.stat().st_size == 0:
            writer.writeheader()
        row = {'time': timestamp}
        for gname, gid in GAMES:
            row[gname] = counts.get(gname, '')
        writer.writerow(row)


# ============================================================
# HTML 图表生成
# ============================================================

def generate_html():
    """从 CSV 生成可视化 HTML — 标签页切换各游戏"""
    rows = load_csv()
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

    # 保存 CSV
    append_csv(datetime.now().strftime('%Y-%m-%d %H:%M'), counts)
    log(f'CSV 已保存: {CSV_FILE}')

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
