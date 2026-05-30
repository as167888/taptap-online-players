#!/usr/bin/env python3
"""
TapTap 游戏在线人数追踪 — 链式翻页版
用法:
  python tracker_chain.py                       # 抓取所有游戏
  python tracker_chain.py --games 714123,172664 # 指定游戏
  python tracker_chain.py --html-only           # 仅生成 HTML
  python tracker_chain.py --delay 1.0           # 自定义请求间隔

输出文件:
  online_chain.csv   — 历史数据 (与 tracker.py 的 online_history.csv 区分)
  online_chain.html  — 可视化图表
"""

import sys, io, json, csv, time, hmac, hashlib, base64, random, re, os
import urllib.parse, requests
from pathlib import Path
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ============================================================
# 配置
# ============================================================
SCRIPT_DIR = Path(__file__).parent
CSV_FILE = SCRIPT_DIR / "online_chain.csv"
HTML_FILE = SCRIPT_DIR / "online_chain.html"

KID = os.environ.get('TAPTAP_KID', 'CG5uaCTyrJBn9QBopp3plUuN2WE6dlGVbj22j3zm')
MAC_KEY = os.environ.get('TAPTAP_MAC_KEY', 'CZ5uaCTytoWFIi4JuzhYXUb3gIcCHtz8gm4uXmBu')
API_HOST = 'api.taptapdada.com'
X_UA = 'V=1&PN=TapPC&VN=2026.5.19-rel.5&VN_CODE=2026051905&CH=organic-direct_index_d20260425--260425ayD0RBcx9pod&OS=windows&OSV=10.0.26200&LANG=zh_CN&UID=2802356a81894c5dae8768bc07c5e29d&SR=1920x1080&VID=658693348'
X_UA_ENC = urllib.parse.quote(X_UA, safe='')

REQUEST_DELAY = 5.0

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


def log(msg):
    line = f'[{datetime.now().strftime("%H:%M:%S")}] {msg}'
    print(line, flush=True)


# ============================================================
# API 请求
# ============================================================

def api_get(path):
    sep = '&' if '?' in path else '?'
    fp = f'{path}{sep}X-UA={X_UA_ENC}'
    ts = str(int(time.time()))
    nonce = ''.join(random.choice('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789') for _ in range(8))
    p = urllib.parse.urlparse(fp)
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
    session = requests.Session()
    session.trust_env = False
    return session.get(f'https://{API_HOST}{fp}', headers=headers, timeout=15)


# ============================================================
# 链式翻页计数
# ============================================================

def count_online_chain(game_id, game_name, limit=50):
    """链式翻页: 从 dw_offset=0 开始，跟 next_page 走到底，返回 (去重人数, 玩家详情列表, 游标轨迹)"""
    all_players = {}  # user_id -> player info
    cursor_trace = []  # 记录每页的翻页游标
    page = 0
    current_path = f'/group/v1/online-players?app_id={game_id}&dw_offset=0&limit={limit}'

    while current_path and page < 1000:
        page += 1
        # 记录当前请求的 dw_offset
        m_req = re.search(r'dw_offset=(\d+)', current_path)
        req_offset = m_req.group(1) if m_req else '?'

        resp = api_get(current_path)
        time.sleep(REQUEST_DELAY)

        if not resp or resp.status_code != 200:
            cursor_trace.append({'page': page, 'req_offset': req_offset, 'next_offset': None, 'count': 0, 'cumulative': len(all_players), 'error': f'HTTP{resp.status_code if resp else "err"}'})
            if page == 1:
                return None, [], cursor_trace
            log(f'    [{game_name}] 第{page}页 HTTP{resp.status_code if resp else "err"}，停止')
            break

        data = resp.json()
        lst = data.get('data', {}).get('list', [])
        next_url = data.get('data', {}).get('next_page', '')

        # 记录游标
        m_next = re.search(r'dw_offset=(\d+)', next_url) if next_url else None
        next_offset = m_next.group(1) if m_next else (None if not next_url else '?')
        cursor_trace.append({
            'page': page, 'req_offset': req_offset, 'next_offset': next_offset,
            'count': len(lst), 'cumulative': len(all_players) + len(lst),
        })

        if not lst:
            log(f'    [{game_name}] 第{page}页 空列表，翻页结束')
            break

        new = 0
        for p in lst:
            u = p.get('user', {})
            uid = u.get('id')
            if uid and uid not in all_players:
                act = p.get('activity_status', {})
                all_players[uid] = {
                    'user_id': uid,
                    'name': u.get('name', ''),
                    'nickname': u.get('nickname', ''),
                    'spent': p.get('spent', 0),
                    'last_played_time': p.get('last_played_time', 0),
                    'activity_game': act.get('label', {}).get('text', ''),
                    'activity_app_id': act.get('label', {}).get('app_id', ''),
                }
                new += 1

        if page <= 5:
            log(f'    [{game_name}] 第{page:>3}页 dw_offset={req_offset:>5} +{new}({len(lst)}条) ={len(all_players)}')
        elif page % 5 == 0:
            log(f'    [{game_name}] 第{page:>3}页 +{new} ={len(all_players)} 累计')
        else:
            print(f'  [{game_name}] p{page} +{new}={len(all_players)}', flush=True)

        if not next_url:
            log(f'    [{game_name}] 无 next_page，翻页结束')
            break

        m = re.search(r'dw_offset=(\d+)', next_url)
        if m:
            current_path = f'/group/v1/online-players?app_id={game_id}&dw_offset={m.group(1)}&limit={limit}'
        else:
            log(f'    [{game_name}] next_page 解析失败')
            break

    return len(all_players), list(all_players.values()), cursor_trace


# ============================================================
# CSV 操作
# ============================================================

def load_csv():
    if not CSV_FILE.exists():
        return []
    rows = []
    with open(CSV_FILE, 'r', encoding='utf-8', newline='') as f:
        for row in csv.DictReader(f):
            rows.append(row)
    return rows


def append_csv(timestamp, counts, game_list):
    hour_key = timestamp[:13]
    # 合并新旧字段名，防止不同次运行游戏列表不一致导致丢列
    new_fieldnames = ['time'] + [g[0] for g in game_list]
    all_fieldnames = list(new_fieldnames)

    rows = []
    updated = False
    if CSV_FILE.exists() and CSV_FILE.stat().st_size > 0:
        with open(CSV_FILE, 'r', encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            if reader.fieldnames:
                for fn in reader.fieldnames:
                    if fn not in all_fieldnames:
                        all_fieldnames.append(fn)
            for row in reader:
                if row['time'][:13] == hour_key:
                    for gname in [g[0] for g in game_list]:
                        old_val = int(row.get(gname, 0) or 0)
                        new_val = counts.get(gname, 0) or 0
                        row[gname] = max(old_val, new_val)
                    updated = True
                rows.append(row)

    if not updated:
        row = {'time': timestamp}
        for gname in [g[0] for g in game_list]:
            row[gname] = counts.get(gname, '')
        rows.append(row)

    with open(CSV_FILE, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=all_fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


# ============================================================
# HTML 生成
# ============================================================

def load_game_info():
    """读取游戏基本信息 (来自 tracker.py 的 game_info.json)"""
    gi_file = SCRIPT_DIR.parent / "game_info.json"
    if gi_file.exists():
        with open(gi_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def generate_html(game_list):
    rows = load_csv()
    if not rows:
        log("CSV 为空，跳过 HTML 生成")
        return

    game_info = load_game_info()
    timestamps = [r['time'] for r in rows]
    series = {}
    for gname, _ in game_list:
        vals = []
        for r in rows:
            v = r.get(gname, '')
            vals.append(int(v) if v and v.strip() else None)
        series[gname] = vals

    gids = [g[0] for g in game_list]
    latest = {g: next((v for v in reversed(series[g]) if v is not None), 0) for g in gids}
    # 按 gids 对应 app_id 排序
    gid_to_name = {g[0]: g[0] for g in game_list}
    gname_to_id = {g[0]: g[1] for g in game_list}
    top_games = sorted(gids, key=lambda g: latest.get(g, 0), reverse=True)

    colors = ["#FF6384", "#36A2EB", "#FFCE56", "#4BC0C0", "#9966FF", "#FF9F40",
              "#7CB342", "#E91E63", "#00BCD4", "#FF5722", "#9C27B0", "#3F51B5",
              "#009688", "#F44336", "#607D8B", "#CDDC39"]

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TapTap 游戏在线人数追踪 (链式)</title>
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
<h3>游戏列表 (链式)</h3>
<button class="active" onclick="showPage('overview')">总览</button>
'''

    for i, gname in enumerate(top_games):
        html += f'<button onclick="showPage(\'game{i}\')">{gname}</button>\n'

    html += '</div>\n<div class="main">\n'

    # ---- 总览页 ----
    html += '<div id="page-overview" class="page active">\n'
    html += f'<h2>全部游戏</h2>\n'
    html += f'<p class="meta">数据范围: {timestamps[0]} ~ {timestamps[-1]} | {len(timestamps)} 个数据点 | dw_offset 链式翻页</p>\n'
    html += '<div class="stats">\n'

    for i, gname in enumerate(top_games):
        s = [v for v in series[gname] if v is not None]
        cur = s[-1] if s else 0
        prev = s[-2] if len(s) >= 2 else cur
        change_html = ''
        if prev > 0:
            pct = (cur - prev) / prev * 100
            if pct > 1: change_html = f'<span class="up">▲{pct:.0f}%</span>'
            elif pct < -1: change_html = f'<span class="down">▼{abs(pct):.0f}%</span>'
            else: change_html = '<span class="flat">─</span>'
        html += f'''<div class="stat-card" style="cursor:pointer" onclick="showPage('game{i}')">
<div class="label">{gname}</div>
<div class="value">{cur:,}</div>
<div class="change">{change_html}</div>
</div>\n'''
    html += '</div>\n'
    html += '<div class="chart-wrap"><canvas id="chartOverview"></canvas></div>\n</div>\n'

    # 总览页 JS
    datasets_json = []
    for i, gname in enumerate(top_games):
        vals = series[gname]
        c = colors[i % len(colors)]
        datasets_json.append(json.dumps({
            'label': gname, 'data': vals,
            'borderColor': c, 'backgroundColor': c + '20',
            'borderWidth': 1.5, 'pointRadius': 1, 'tension': 0.3, 'fill': False,
        }))
    html += f'''<script>
const allSeries = {json.dumps(series, ensure_ascii=False)};
const allNames = {json.dumps(top_games, ensure_ascii=False)};
const labels = {json.dumps(timestamps, ensure_ascii=False)};
new Chart(document.getElementById('chartOverview').getContext('2d'), {{
    type: 'line',
    data: {{ labels, datasets: [{','.join(datasets_json)}] }},
    options: {{
        responsive: true, maintainAspectRatio: false,
        interaction: {{ mode: 'nearest', intersect: false, axis: 'x' }},
        plugins: {{ legend: {{ position: 'bottom', labels: {{ color: '#ccc', usePointStyle: true, padding: 12, font: {{ size:11 }} }} }} }},
        scales: {{
            x: {{ ticks: {{ color: '#888', maxTicksLimit: 20, maxRotation: 45 }} }},
            y: {{ ticks: {{ color: '#888', callback: v => v>=1000 ? (v/1000).toFixed(1)+'k' : v }} }}
        }}
    }}
}});
function showPage(id) {{
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.getElementById('page-' + id).classList.add('active');
    document.querySelectorAll('.sidebar button').forEach(b => b.classList.remove('active'));
    event.target.classList.add('active');
}}
</script>\n'''

    # ---- 各游戏详情页 ----
    for i, gname in enumerate(top_games):
        s = series[gname]
        vals = [v for v in s if v is not None]
        cur = vals[-1] if vals else 0
        max_val = max(vals) if vals else 0
        min_val = min(vals) if vals else 0
        avg_val = sum(vals) / len(vals) if vals else 0
        prev = vals[-2] if len(vals) >= 2 else cur
        change_html = ''
        if prev > 0:
            pct = (cur - prev) / prev * 100
            if pct > 1: change_html = f'<span class="up">▲{pct:.0f}%</span>'
            elif pct < -1: change_html = f'<span class="down">▼{abs(pct):.0f}%</span>'
            else: change_html = '<span class="flat">─</span>'

        c = colors[i % len(colors)]
        app_id = gname_to_id.get(gname, '')
        gi = game_info.get(app_id, {})

        html += f'<div id="page-game{i}" class="page">\n'
        html += f'<h2>{gname}</h2>\n'

        # 游戏信息卡片
        if gi:
            tags_html = ' '.join(f'<span style="display:inline-block;background:#1a1a3e;padding:2px 8px;border-radius:3px;font-size:11px;margin:2px">{t}</span>' for t in gi.get('tags', [])[:5])
            fans = gi.get('fans_count', 0)
            reviews = gi.get('review_count', 0)
            fans_wan = fans / 10000
            review_wan = reviews / 10000
            latest_rev_count = gi.get('latest_review_count', 0)
            latest_rev_wan = latest_rev_count / 10000
            pc_dl = gi.get('pc_download_count', 0)
            pc_dl_wan = pc_dl / 10000
            html += '<div style="display:flex;gap:16px;align-items:flex-start;margin-bottom:16px;background:#16213e;border-radius:8px;padding:16px">\n'
            if gi.get('icon_url'):
                html += f'<img src="{gi["icon_url"]}" style="width:64px;height:64px;border-radius:12px;flex-shrink:0" referrerpolicy="no-referrer" onerror="this.style.display=\'none\'">\n'
            html += '<div style="flex:1">\n'
            html += f'<div style="font-size:13px;color:#aaa;margin-bottom:6px">{tags_html}</div>\n'
            html += '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px 16px;font-size:13px">\n'
            html += f'<div><span style="color:#888;font-size:11px">游戏 ID</span><br><span style="font-size:22px;font-weight:700">{app_id}</span></div>\n'
            html += f'<div><span style="color:#888;font-size:11px">游戏名称</span><br><span style="font-size:22px;font-weight:700">{gi.get("title", gname)}</span></div>\n'
            html += f'<div><span style="color:#888;font-size:11px">粉丝数</span><br><span style="font-size:22px;font-weight:700">{fans_wan:.1f}万</span></div>\n'
            html += f'<div><span style="color:#888;font-size:11px">评价总数</span><br><span style="font-size:22px;font-weight:700">{review_wan:.1f}万</span></div>\n'
            html += f'<div><span style="color:#888;font-size:11px">当前评分</span><br><span style="color:#FFCE56;font-size:22px;font-weight:700">{gi.get("score","?")}</span><span style="color:#888"> / 10</span></div>\n'
            html += f'<div><span style="color:#888;font-size:11px">最新版本评分</span><br><span style="font-size:22px;font-weight:700">{gi.get("latest_version_score","?")}</span></div>\n'
            html += f'<div><span style="color:#888;font-size:11px">最近 7 天评分</span><br><span style="font-size:22px;font-weight:700">{gi.get("latest_score","?")}</span><span style="color:#888;font-size:13px"> ({latest_rev_wan:.1f}万评价)</span></div>\n'
            html += f'<div><span style="color:#888;font-size:11px">开发商</span><br><span style="font-size:22px;font-weight:700">{gi.get("developer","?")}</span></div>\n'
            if pc_dl > 0:
                html += f'<div><span style="color:#888;font-size:11px">PC下载</span><br><span style="font-size:22px;font-weight:700">{pc_dl_wan:.1f}万</span></div>\n'
            if gi.get('update_date'):
                html += f'<div><span style="color:#888;font-size:11px">更新日期</span><br><span style="font-size:22px;font-weight:700">{gi["update_date"]}</span></div>\n'
            html += '</div></div></div>\n'

        html += f'<p class="meta">{len(s)} 个数据点 | {timestamps[0]} ~ {timestamps[-1]}</p>\n'
        html += '<div class="stats">\n'
        html += f'<div class="stat-card"><div class="label">当前在线</div><div class="value">{cur:,}</div><div class="change">{change_html}</div></div>\n'
        html += f'<div class="stat-card"><div class="label">最高</div><div class="value">{max_val:,}</div></div>\n'
        html += f'<div class="stat-card"><div class="label">最低</div><div class="value">{min_val:,}</div></div>\n'
        html += f'<div class="stat-card"><div class="label">平均</div><div class="value">{avg_val:,.0f}</div></div>\n'
        html += '</div>\n'
        html += f'<div class="chart-wrap"><canvas id="chartGame{i}"></canvas></div>\n'

        ds = json.dumps({'label': gname, 'data': s,
                         'borderColor': c, 'backgroundColor': c + '30',
                         'borderWidth': 2, 'pointRadius': 3, 'pointHoverRadius': 5,
                         'tension': 0.3, 'fill': True})
        html += f'''<script>
new Chart(document.getElementById('chartGame{i}').getContext('2d'), {{
    type: 'line',
    data: {{ labels, datasets: [{ds}] }},
    options: {{
        responsive: true, maintainAspectRatio: false,
        interaction: {{ mode: 'nearest', intersect: false, axis: 'x' }},
        plugins: {{ legend: {{ display: false }} }},
        scales: {{
            x: {{ ticks: {{ color: '#888', maxTicksLimit: 20, maxRotation: 45 }} }},
            y: {{ ticks: {{ color: '#888', callback: v => v>=1000 ? (v/1000).toFixed(1)+'k' : v }} }}
        }}
    }}
}});
</script>\n'''
        html += '</div>\n'

    html += f'''</div></div>
<div class="footer">链式翻页追踪 | 更新于 {datetime.now().strftime("%Y-%m-%d %H:%M")} | 方法: dw_offset next_page 去重计数 | <a href="../online_chart.html" style="color:#888">旧版数据</a></div>
</body></html>'''

    with open(HTML_FILE, 'w', encoding='utf-8') as f:
        f.write(html)
    log(f'HTML 已生成: {HTML_FILE}')


# ============================================================
# 主程序
# ============================================================

LOG_DIR = SCRIPT_DIR / "scan_logs"

def fetch_all(game_list):
    now = datetime.now()
    scan_id = now.strftime('%Y%m%d_%H%M')
    LOG_DIR.mkdir(exist_ok=True)
    log(f'链式翻页抓取 {len(game_list)} 款游戏  批次: {scan_id}')
    log(f'间隔: 页{REQUEST_DELAY}s/游戏2s')
    log('-' * 50)

    counts = {}
    success = 0
    start_time = time.time()

    for i, (gname, gid) in enumerate(game_list):
        t0 = time.time()
        log(f'[{i+1}/{len(game_list)}] {gname} (ID={gid}) ...')
        total, players, cursor_trace = count_online_chain(gid, gname)
        elapsed = time.time() - t0

        if total is not None:
            counts[gname] = total
            success += 1

            # 状态分布汇总
            from collections import Counter
            status_counter = Counter(p.get('activity_game', '') or '未知' for p in players)
            status_summary = [{'status': s, 'count': c, 'pct': round(c/total*100, 1) if total else 0}
                            for s, c in status_counter.most_common()]

            # 保存本次扫描的玩家详情 — 按游戏/日期 分目录
            date_str = scan_id[:8]  # YYYYMMDD
            game_log_dir = LOG_DIR / gname / date_str
            game_log_dir.mkdir(parents=True, exist_ok=True)
            log_file = game_log_dir / f'{scan_id}_{gname}.json'
            with open(log_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'scan_id': scan_id,
                    'game_id': gid,
                    'game_name': gname,
                    'scan_time': now.strftime('%Y-%m-%d %H:%M:%S'),
                    'unique_players': total,
                    'elapsed_seconds': round(elapsed, 1),
                    'total_pages': len(cursor_trace),
                    'cursor_trace': cursor_trace,
                    'status_summary': status_summary,
                    'players': sorted(players, key=lambda x: x.get('spent', 0), reverse=True),
                }, f, ensure_ascii=False, indent=2)

            log(f'  OK {gname}: {total:,} 人 ({elapsed:.1f}s) 日志: {gname}/{date_str}/{log_file.name}')
            log(f'  ── 状态分布 ──')
            for s in status_summary:
                bar_len = int(s['pct'] / 2)
                bar = '█' * bar_len
                log(f'    {s["status"]:12s} {s["count"]:>5}人 ({s["pct"]:5.1f}%) {bar}')
        else:
            counts[gname] = 0
            log(f'  FAIL {gname} ({elapsed:.1f}s)')

        if i < len(game_list) - 1:
            time.sleep(2)

    total_time = time.time() - start_time
    now = datetime.now()
    hour_ts = now.strftime('%Y-%m-%d %H:00')
    append_csv(hour_ts, counts, game_list)
    csv_rows = len(load_csv())
    log(f'CSV 已保存: {CSV_FILE} ({csv_rows} 行)')
    generate_html(game_list)
    log(f'完成! {success}/{len(game_list)} 成功, 总耗时 {total_time:.0f}s')


if __name__ == '__main__':
    if '--html-only' in sys.argv:
        generate_html(GAMES)
        sys.exit(0)

    game_list = GAMES

    if '--games' in sys.argv:
        idx = sys.argv.index('--games')
        if idx + 1 < len(sys.argv):
            ids = sys.argv[idx + 1].split(',')
            game_list = [(name, gid) for name, gid in GAMES if gid in ids]
            if not game_list:
                print(f'未找到匹配游戏: {ids}')
                sys.exit(1)

    if '--delay' in sys.argv:
        idx = sys.argv.index('--delay')
        if idx + 1 < len(sys.argv):
            REQUEST_DELAY = float(sys.argv[idx + 1])

    fetch_all(game_list)
