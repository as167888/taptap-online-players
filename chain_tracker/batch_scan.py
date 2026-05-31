#!/usr/bin/env python3
"""
TapTap PC 游戏批量在线人数扫描器 — 全部游戏 dw_offset 链式翻页

用法:
  python batch_scan.py                      # 扫描全部 8,653 款游戏
  python batch_scan.py --resume             # 续扫（跳过已完成的游戏）
  python batch_scan.py --games 714119,45213 # 只扫指定游戏
  python batch_scan.py --delay 0.8          # 自定义请求间隔(默认0.6s)
  python batch_scan.py --no-proxy           # 直连（不用代理）

输出:
  batch_scans/{批次}/by_game/{游戏ID}_{游戏名}.json  — 每款游戏的扫描结果（含完整玩家列表）
  batch_scans/{批次}/_summary.json                   — 汇总统计
  batch_scans/{批次}/_progress.json                  — 进度文件（续扫用）
"""

import sys, io, json, time, hmac, hashlib, base64, random, re, os
import urllib.parse, requests
from pathlib import Path
from datetime import datetime
from collections import Counter

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ============================================================
# 配置
# ============================================================
SCRIPT_DIR = Path(__file__).parent
OUTPUT_DIR = SCRIPT_DIR / "batch_scans"
GAMES_FILE = SCRIPT_DIR / "pc_games.json"

KID = os.environ.get('TAPTAP_KID', 'CG5uaCTyrJBn9QBopp3plUuN2WE6dlGVbj22j3zm')
MAC_KEY = os.environ.get('TAPTAP_MAC_KEY', 'CZ5uaCTytoWFIi4JuzhYXUb3gIcCHtz8gm4uXmBu')
API_HOST = 'api.taptapdada.com'
X_UA = 'V=1&PN=TapPC&VN=2026.5.19-rel.5&VN_CODE=2026051905&CH=organic-direct_index_d20260425--260425ayD0RBcx9pod&OS=windows&OSV=10.0.26200&LANG=zh_CN&UID=2802356a81894c5dae8768bc07c5e29d&SR=1920x1080&VID=658693348'
X_UA_ENC = urllib.parse.quote(X_UA, safe='')

REQUEST_DELAY = 0.6       # 请求间隔（秒）
PAUSE_EVERY_N = 80        # 每 N 次请求暂停
PAUSE_SECONDS = 6.0       # 暂停时长
CHAIN_LIMIT = 50          # 链式翻页每页条数
USE_PROXY = True
PROXY_URL = 'http://127.0.0.1:7993'

# ============================================================
# 日志 & 节流
# ============================================================

_request_count = 0

def log(msg):
    line = f'[{datetime.now().strftime("%H:%M:%S")}] {msg}'
    print(line, flush=True)

def maybe_pause():
    global _request_count
    _request_count += 1
    if _request_count % PAUSE_EVERY_N == 0:
        log(f'  ⏸ 已 {_request_count} 次请求，暂停 {PAUSE_SECONDS}s ...')
        time.sleep(PAUSE_SECONDS)

# ============================================================
# API 请求
# ============================================================

def build_session():
    session = requests.Session()
    session.trust_env = False
    if USE_PROXY:
        session.proxies = {'http': PROXY_URL, 'https': PROXY_URL}
    return session

def api_get(path, session):
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
        'Host': API_HOST,
        'Accept': 'application/json',
        'User-Agent': 'TapTap/2026.5.19-rel.5 (Build 2026051905/1d8a57a6) TapPC-Main/2026.5.19-rel.5',
        'Authorization': f'MAC id="{KID}",ts="{ts}",nonce="{nonce}",mac="{sig}"',
    }
    return session.get(f'https://{API_HOST}{fp}', headers=headers, timeout=15)

# ============================================================
# 链式翻页扫描
# ============================================================

def chain_scan_game(game_id, game_name, session):
    """dw_offset 链式翻页，返回 (unique_count, players_list, cursor_trace, status_summary)"""
    all_players = {}
    cursor_trace = []
    page = 0
    current_path = f'/group/v1/online-players?app_id={game_id}&dw_offset=0&limit={CHAIN_LIMIT}'

    while current_path and page < 1000:
        page += 1
        m_req = re.search(r'dw_offset=(\d+)', current_path)
        req_offset = m_req.group(1) if m_req else '?'

        resp = api_get(current_path, session)
        time.sleep(REQUEST_DELAY)
        maybe_pause()

        if not resp or resp.status_code != 200:
            cursor_trace.append({
                'page': page, 'req_offset': req_offset, 'next_offset': None,
                'count': 0, 'cumulative': len(all_players),
                'error': f'HTTP{resp.status_code if resp else "err"}'
            })
            if page == 1:
                return 0, [], cursor_trace, []
            log(f'    [{game_name}] 第{page}页 HTTP{resp.status_code if resp else "err"}，停止')
            break

        data = resp.json().get('data', {})
        lst = data.get('list', [])
        next_url = data.get('next_page', '')

        m_next = re.search(r'dw_offset=(\d+)', next_url) if next_url else None
        next_offset = m_next.group(1) if m_next else (None if not next_url else '?')
        cursor_trace.append({
            'page': page, 'req_offset': req_offset, 'next_offset': next_offset,
            'count': len(lst), 'cumulative': len(all_players) + len(lst),
        })

        if not lst:
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

        if page <= 3 or page % 10 == 0:
            log(f'    [{game_name}] p{page:>3} dw={req_offset:>5} +{new}({len(lst)}条) ={len(all_players)}')
        else:
            print(f'  [{game_name}] p{page} +{new}={len(all_players)}', flush=True)

        if not next_url:
            break

        m = re.search(r'dw_offset=(\d+)', next_url)
        if m:
            current_path = f'/group/v1/online-players?app_id={game_id}&dw_offset={m.group(1)}&limit={CHAIN_LIMIT}'
        else:
            log(f'    [{game_name}] next_page 解析失败')
            break

    total = len(all_players)
    players_list = list(all_players.values())
    status_counter = Counter(p.get('activity_game', '') or '未知' for p in players_list)
    status_summary = [
        {'status': s, 'count': c, 'pct': round(c / total * 100, 1) if total else 0}
        for s, c in status_counter.most_common()
    ]
    return total, players_list, cursor_trace, status_summary

# ============================================================
# 保存 & 进度
# ============================================================

def save_game_result(batch_dir, game_id, game_name, scan_time, result):
    by_game_dir = batch_dir / "by_game"
    by_game_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r'[\\/*?:"<>|]', '_', game_name)
    json_file = by_game_dir / f'{game_id}_{safe_name}.json'
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return json_file

def save_progress(batch_dir, progress):
    with open(batch_dir / '_progress.json', 'w', encoding='utf-8') as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)

def load_progress(batch_dir):
    pf = batch_dir / '_progress.json'
    if pf.exists():
        with open(pf, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None

# ============================================================
# 主程序
# ============================================================

def main():
    global REQUEST_DELAY, USE_PROXY

    resume_mode = '--resume' in sys.argv
    if '--no-proxy' in sys.argv:
        USE_PROXY = False
    if '--delay' in sys.argv:
        idx = sys.argv.index('--delay')
        if idx + 1 < len(sys.argv):
            REQUEST_DELAY = float(sys.argv[idx + 1])

    # 加载游戏列表
    if not GAMES_FILE.exists():
        log(f'❌ 游戏列表文件不存在: {GAMES_FILE}')
        sys.exit(1)

    with open(GAMES_FILE, 'r', encoding='utf-8') as f:
        all_games_raw = json.load(f)

    all_games = sorted(all_games_raw.items(), key=lambda x: int(x[0]))

    if '--games' in sys.argv:
        idx = sys.argv.index('--games')
        if idx + 1 < len(sys.argv):
            ids = set(sys.argv[idx + 1].split(','))
            all_games = [(gid, gname) for gid, gname in all_games if gid in ids]
            if not all_games:
                log(f'❌ 未找到匹配游戏')
                sys.exit(1)

    total_games = len(all_games)

    # 批次目录 & 续扫
    now = datetime.now()
    scan_id = now.strftime('%Y%m%d_%H%M')
    batch_dir = OUTPUT_DIR / scan_id
    batch_dir.mkdir(parents=True, exist_ok=True)

    scanned_ids = set()
    if resume_mode:
        existing = sorted(OUTPUT_DIR.glob('*'), reverse=True)
        for eb in existing:
            if eb.is_dir() and (eb / '_progress.json').exists():
                p = load_progress(eb)
                if p:
                    batch_dir = eb
                    scan_id = eb.name
                    scanned_ids = set(p.get('completed_ids', []))
                    log(f'📂 续扫: 批次 {scan_id}  已完成 {len(scanned_ids)} 款')
                    break
        if not scanned_ids:
            log('📂 未找到进度文件，从头开始')

    progress = load_progress(batch_dir) or {
        'scan_id': scan_id, 'start_time': now.strftime('%Y-%m-%d %H:%M:%S'),
        'total_games': total_games, 'completed_ids': [], 'failed_ids': [],
        'stats': {'scanned': 0, 'total_requests': 0, 'total_players': 0},
    }
    stats = progress['stats']
    session = build_session()

    log('=' * 60)
    log(f'TapTap PC 游戏批量在线人数扫描 — 全量链式翻页')
    log(f'  批次: {scan_id}  游戏总数: {total_games:,}')
    log(f'  已完成: {len(scanned_ids):,}  待扫描: {total_games - len(scanned_ids):,}')
    log(f'  间隔: {REQUEST_DELAY}s  代理: {PROXY_URL if USE_PROXY else "直连"}')
    log(f'  输出: {batch_dir}')
    log('=' * 60)

    start_time = time.time()
    scanned = stats.get('scanned', 0)
    zero_count = 0

    for i, (gid, gname) in enumerate(all_games):
        if gid in scanned_ids:
            continue

        t0 = time.time()
        pct = (i + 1) / total_games * 100

        # 实时总体进度
        bar_len = 30
        filled = int(bar_len * (i + 1) / total_games)
        bar = '█' * filled + '░' * (bar_len - filled)
        eta = ''
        if scanned > 0:
            elapsed = time.time() - start_time
            rate = elapsed / scanned
            remaining = (total_games - len(scanned_ids) - scanned) * rate
            if remaining > 60:
                eta = f' ETA:{remaining/60:.0f}min'

        log(f'\n[{i+1:>5}/{total_games}] {bar} {pct:.1f}%{eta} | {gname} (ID={gid})')

        total, players, cursor_trace, status_summary = chain_scan_game(gid, gname, session)
        elapsed = time.time() - t0
        scanned += 1
        stats['scanned'] = scanned
        stats['total_players'] += total

        if total == 0:
            zero_count += 1

        # 保存结果
        result = {
            'game_id': gid,
            'game_name': gname,
            'scan_time': now.strftime('%Y-%m-%d %H:%M:%S'),
            'method': 'chain',
            'unique_players': total,
            'elapsed_seconds': round(elapsed, 1),
            'total_pages': len(cursor_trace),
            'cursor_trace': cursor_trace,
            'status_summary': status_summary,
            'players': sorted(players, key=lambda x: x.get('spent', 0), reverse=True),
        }
        save_game_result(batch_dir, gid, gname, now.strftime('%Y-%m-%d %H:%M:%S'), result)

        scanned_ids.add(gid)
        progress['completed_ids'] = list(scanned_ids)
        progress['stats'] = stats
        save_progress(batch_dir, progress)

        # 回显
        pages_str = f'{len(cursor_trace)}页' if cursor_trace else '?'
        log(f'  ✓ {total} 人 / {pages_str} / {elapsed:.0f}s')
        if status_summary:
            for s in status_summary[:3]:
                bar_s = '█' * min(int(s['pct'] / 2), 40)
                log(f'    {s["status"][:15]:15s} {s["count"]:>5}人 ({s["pct"]:5.1f}%) {bar_s}')

        # 游戏间额外间隔
        time.sleep(0.4)

    # ============================================================
    # 汇总
    # ============================================================
    total_elapsed = time.time() - start_time

    all_results = []
    by_game_dir = batch_dir / "by_game"
    if by_game_dir.exists():
        for f in sorted(by_game_dir.glob('*.json')):
            try:
                with open(f, 'r', encoding='utf-8') as fh:
                    all_results.append(json.load(fh))
            except:
                pass
    all_results.sort(key=lambda r: r.get('unique_players', 0), reverse=True)

    summary = {
        'scan_id': scan_id,
        'scan_time': now.strftime('%Y-%m-%d %H:%M:%S'),
        'total_games': total_games,
        'games_scanned': len(all_results),
        'games_failed': len(progress.get('failed_ids', [])),
        'total_requests_made': _request_count,
        'total_players_found': stats.get('total_players', 0),
        'elapsed_seconds': round(total_elapsed, 0),
        'config': {
            'request_delay': REQUEST_DELAY,
            'proxy': PROXY_URL if USE_PROXY else 'direct',
            'chain_limit': CHAIN_LIMIT,
        },
        'top_games': [
            {'game_id': r['game_id'], 'game_name': r['game_name'],
             'online': r['unique_players'], 'pages': r.get('total_pages', 0)}
            for r in all_results[:50]
        ],
        'zero_online_count': sum(1 for r in all_results if r.get('unique_players', 0) == 0),
        'failed_ids': progress.get('failed_ids', []),
    }

    summary_file = batch_dir / '_summary.json'
    with open(summary_file, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    progress['end_time'] = now.strftime('%Y-%m-%d %H:%M:%S')
    save_progress(batch_dir, progress)

    log(f'\n{"=" * 60}')
    log(f'🏁 批量扫描完成!')
    log(f'  扫描游戏: {len(all_results):,} / {total_games:,}')
    log(f'  总请求数: {_request_count:,}')
    log(f'  总玩家记录: {stats.get("total_players", 0):,}')
    log(f'  0人在线: {summary["zero_online_count"]:,} 款')
    log(f'  总耗时: {total_elapsed/60:.0f}min {total_elapsed%60:.0f}s')
    log(f'  汇总: {summary_file}')

    log(f'\n  📊 在线人数 TOP 20:')
    for i, g in enumerate(summary['top_games'][:20]):
        log(f'  {i+1:>3}. {g["game_name"]:25s} (ID={g["game_id"]:>7}) {g["online"]:>6,} 人 [{g["pages"]}页]')


if __name__ == '__main__':
    main()
