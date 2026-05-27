#!/usr/bin/env python3
"""
TapTap 游戏在线人数查询 — 无需抓包，通过本地 Pipe 自动认证

原理:
  TapTap 桌面客户端运行时创建 \\.\pipe\tappc_cn_http 命名管道
  管道背后是 Go 后端服务，自动为请求添加 MAC 认证签名
  因此无需手动处理签名，也不会过期（客户端自动刷新 Token）

用法:
  python tap_online.py 714119        # 查询异环（快速，只看 total）
  python tap_online.py 714119 --full # 翻页到底获取真实总数
  python tap_online.py               # 交互模式

要求:
  TapTap 桌面客户端必须在运行且已登录
"""

import os
import json
import re
import time
import sys
import io
import urllib.parse

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

PIPE_PATH = '\\\\.\\pipe\\tappc_cn_http'
API_HOST = 'api.taptapdada.com'
X_UA = (
    'V=1&PN=TapPC&VN=2026.5.19-rel.5&VN_CODE=2026051905'
    '&CH=organic-direct_index_d20260425--260425ayD0RBcx9pod'
    '&OS=windows&OSV=10.0.26200&LANG=zh_CN'
    '&UID=2802356a81894c5dae8768bc07c5e29d'
    '&SR=1920x1080&VID=658693348'
)

# 已知游戏
KNOWN_GAMES = {
    '714119': '异环', '172664': '火炬之光：无限', '168332': '原神',
    '188212': '崩坏：星穹铁道', '70056': '和平精英', '330259': '明日方舟',
    '234280': '鸣潮', '314057': '绝区零', '45213': '我的世界',
    '167270': '蛋仔派对', '194370': '幻塔',
}


def check_pipe():
    """检查 Pipe 是否可用"""
    if not os.path.exists(PIPE_PATH):
        print(f"错误: 命名管道不存在 ({PIPE_PATH})")
        print("请确保 TapTap 桌面客户端正在运行")
        return False
    return True


def api_request(path):
    """通过 Pipe 发送 API 请求，自动获得 MAC 认证"""
    fd = os.open(PIPE_PATH, os.O_RDWR | os.O_BINARY)
    x_ua_enc = urllib.parse.quote(X_UA, safe='')

    # 拼接 URL
    sep = '&' if '?' in path else '?'
    full_path = f'{path}{sep}X-UA={x_ua_enc}'

    req = (
        f'GET {full_path} HTTP/1.1\r\n'
        f'Host: {API_HOST}\r\n'
        'Accept: application/json\r\n'
        'User-Agent: TapTap/2026.5.19-rel.5 (Build 2026051905/1d8a57a6) TapPC-Main/2026.5.19-rel.5\r\n'
        'X-TAPPC-PROXY: taptap\r\n'
        'Connection: close\r\n'
        '\r\n'
    )
    os.write(fd, req.encode())

    resp = b''
    while True:
        try:
            chunk = os.read(fd, 8192)
            if not chunk:
                break
            resp += chunk
        except BlockingIOError:
            time.sleep(0.05)
        except:
            break
    os.close(fd)

    if b'\r\n\r\n' not in resp:
        return None

    hdr, body = resp.split(b'\r\n\r\n', 1)

    # Dechunk
    if b'Transfer-Encoding: chunked' in hdr:
        dechunked = b''
        while body:
            sz_end = body.find(b'\r\n')
            if sz_end < 0:
                break
            chunk_size = int(body[:sz_end], 16)
            if chunk_size == 0:
                break
            dechunked += body[sz_end + 2:sz_end + 2 + chunk_size]
            body = body[sz_end + 2 + chunk_size + 2:]
        body = dechunked

    try:
        return json.loads(body)
    except:
        return None


def get_online_count(game_id, full_count=False):
    """
    获取游戏在线人数
    full_count=True: 翻页到底获取真实总数（较慢）
    full_count=False: 只取第一页，看 total 字段（快速，但 total 可能被截断为 100）
    """
    if full_count:
        return _count_all(game_id)

    data = api_request(f'/group/v1/online-players?app_id={game_id}&from=0&limit=1')
    if not data or not data.get('success'):
        return None, data.get('data', {}).get('msg', 'unknown error') if data else 'no response'

    # total 字段可能被缓存/截断为 100
    total = data['data'].get('total', 0)
    cached = 'cached_total' in data['data'].get('next_page', '')
    return total, cached


def _count_all(game_id):
    """翻页到底获取真实在线人数"""
    total = 0
    page = 0
    path = f'/group/v1/online-players?app_id={game_id}&from=0&limit=50'

    print('  翻页计数中...', end='', flush=True)
    while path and page < 300:
        page += 1
        data = api_request(path)
        if not data:
            break

        lst = data.get('data', {}).get('list', [])
        next_url = data.get('data', {}).get('next_page', '')

        if not lst:
            break

        total += len(lst)
        path = next_url.replace(f'https://{API_HOST}', '') if next_url else ''

        if page % 20 == 0:
            print(f' {total}...', end='', flush=True)

    print(f' 完成 ({page} 页)')
    return total


def search_game(keyword):
    """通过名称搜索游戏（模糊匹配）"""
    # 精确匹配已知列表
    if keyword in KNOWN_GAMES:
        return KNOWN_GAMES[keyword], keyword

    for gid, name in KNOWN_GAMES.items():
        if keyword in name:
            return gid, name

    # 精确 ID
    if keyword.isdigit():
        return keyword, f'ID={keyword}'

    return None, None


def main():
    if not check_pipe():
        sys.exit(1)

    args = sys.argv[1:]
    full_mode = '--full' in args or '-f' in args
    args = [a for a in args if not a.startswith('--') and not a.startswith('-')]

    if args:
        game_id, game_name = search_game(args[0])
        if not game_id:
            print(f'未找到游戏: {args[0]}')
            sys.exit(1)
    else:
        # 交互模式
        print("已知游戏:")
        for gid, name in sorted(KNOWN_GAMES.items(), key=lambda x: int(x[0])):
            print(f"  {gid}: {name}")
        game_id = input("\n输入游戏 ID 或名称: ").strip()
        game_id, game_name = search_game(game_id)
        if not game_id:
            print(f'未找到游戏')
            sys.exit(1)

    print(f'查询: {game_name} (ID={game_id})')
    print()

    if full_mode:
        total = get_online_count(game_id, full_count=True)
        print(f'\n{game_name} 真实在线人数: {total:,} 人')
    else:
        total, cached = get_online_count(game_id, full_count=False)
        print(f'{game_name} 在线人数: {total}')
        if cached:
            print('(注: 此数值可能是缓存/截断值，使用 --full 获取精确总数)')
        elif total >= 100:
            print('(使用 --full 获取精确总数)')


if __name__ == '__main__':
    main()
