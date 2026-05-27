"""批量查询多款游戏在线人数 — 带请求间隔防限流"""
import urllib.parse, time, hmac, hashlib, base64, random, string, requests, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

KID = ''   # 从 config.taptap 解密获取，或设置环境变量 TAPTAP_KID
MAC_KEY = ''  # 从 config.taptap 解密获取，或设置环境变量 TAPTAP_MAC_KEY
import os as _os
KID = _os.environ.get('TAPTAP_KID', KID)
MAC_KEY = _os.environ.get('TAPTAP_MAC_KEY', MAC_KEY)
API_HOST = 'api.taptapdada.com'
X_UA = 'V=1&PN=TapPC&VN=2026.5.19-rel.5&VN_CODE=2026051905&CH=organic-direct_index_d20260425--260425ayD0RBcx9pod&OS=windows&OSV=10.0.26200&LANG=zh_CN&UID=2802356a81894c5dae8768bc07c5e29d&SR=1920x1080&VID=658693348'
X_UA_ENC = urllib.parse.quote(X_UA, safe='')

# 请求间隔 (秒) — 避免触发 API 限流 405
PAGE_DELAY = 0.5    # 每页之间的间隔
GAME_DELAY = 2.0    # 每个游戏之间的间隔

# 游戏列表 (名称, ID)
GAMES = [
    ('火炬之光：无限', '172664'),
    ('异环', '714119'),
    ('洛克王国：世界', '188212'),
    ('鸣潮', '234280'),
    ('心动小镇', '45213'),
    ('原神', '168332'),
    ('超自然行动组', '714123'),
    ('明日方舟：终末地', '232326'),
    ('和平精英', '70056'),
    ('三角洲行动', '330259'),
    ('伊瑟', '759688'),
    ('明日方舟', '337799'),
    ('崩坏：星穹铁道', '224267'),
    ('燕云十六声', '187811'),
]

def api_req(full_path):
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
    return requests.get(f'https://{API_HOST}{full_path}', headers=headers, timeout=10)

def count_online(game_id):
    current_path = f'/group/v1/online-players?app_id={game_id}&from=0&limit=50&X-UA={X_UA_ENC}'
    total = 0
    page = 0
    while current_path and page < 500:
        page += 1
        resp = api_req(current_path)
        if resp.status_code != 200:
            if page == 1:
                return 0, page, f'HTTP {resp.status_code}'
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
        current_path = f'{next_path}&X-UA={X_UA_ENC}'

        # 页间延迟
        time.sleep(PAGE_DELAY)

        if page % 20 == 0:
            print(f'{total}...', end='', flush=True)

    return total, page, None

# 查询
print('批量查询在线人数 (带请求间隔)')
print('=' * 65)
results = []

for i, (gname, gid) in enumerate(GAMES):
    print(f'\n{gname} (ID={gid})...', end=' ', flush=True)

    # 游戏间延迟 (第一个游戏不延迟)
    if i > 0:
        time.sleep(GAME_DELAY)

    total, pages, err = count_online(gid)
    results.append((gname, gid, total, pages, err))

    if err:
        print(f'错误: {err}')
    else:
        print(f'{total:,} 人 ({pages} 页)')

# 排序
results.sort(key=lambda x: -x[2])

print(f'\n\n{"="*65}')
print(f'{"游戏":22s} {"ID":>8s} {"在线人数":>10s}   {"页数":>5s}')
print('-' * 65)
for name, gid, total, pages, err in results:
    mark = ''
    if err:
        mark = f' [{err}]'
    elif total == 0 and pages <= 1:
        mark = ' [0或无]'
    print(f'{name:22s} {gid:>8s} {total:>10,}   {pages:>5}{mark}')
print('=' * 65)
print(f'查询时间: {time.strftime("%Y-%m-%d %H:%M:%S")}')
