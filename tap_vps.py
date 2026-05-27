#!/usr/bin/env python3
"""
TapTap 在线人数查询 — VPS 独立部署版

无需 TapTap 客户端，直接通过 MAC 签名调用 API。
credentials 从 config.taptap 解密获取，或手动设置。

用法:
  python tap_vps.py 714119              # 自动读取 config 文件
  python tap_vps.py 714119 --full       # 翻页到底获取精确总数

VPS 部署:
  1. 从 Windows 客户端解密 config.taptap，提取 kid + mac_key
  2. 设置环境变量或直接填入脚本
  3. pip install requests
  4. python tap_vps.py <game_id>
"""

import os
import sys
import io
import time
import json
import hmac
import hashlib
import base64
import random
import string
import requests
import urllib.parse
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ============================================================
# 凭证配置 (从 config.taptap 解密获取)
# ============================================================
# 方式 1: 环境变量
KID = os.environ.get("TAPTAP_KID", "")
MAC_KEY = os.environ.get("TAPTAP_MAC_KEY", "")
MAC_ALGORITHM = os.environ.get("TAPTAP_MAC_ALGORITHM", "hmac-sha-1")

# 方式 2: 直接填入 (从 config.taptap 解密得到的值)
# 注意: 请替换为你自己的凭证，或使用环境变量
if not KID:
    KID = ""
if not MAC_KEY:
    MAC_KEY = ""
if MAC_ALGORITHM == "hmac-sha-1":
    MAC_ALGORITHM = "hmac-sha-1"

# ============================================================
# API 配置
# ============================================================
API_HOST = "api.taptapdada.com"
X_UA = (
    "V=1&PN=TapPC&VN=2026.5.19-rel.5&VN_CODE=2026051905"
    "&CH=organic-direct_index_d20260425--260425ayD0RBcx9pod"
    "&OS=windows&OSV=10.0.26200&LANG=zh_CN"
    "&UID=2802356a81894c5dae8768bc07c5e29d"
    "&SR=1920x1080&VID=658693348"
)

KNOWN_GAMES = {
    '714119': '异环', '172664': '火炬之光：无限', '168332': '原神',
    '188212': '崩坏：星穹铁道', '70056': '和平精英', '330259': '明日方舟',
    '234280': '鸣潮', '314057': '绝区零', '45213': '我的世界',
    '167270': '蛋仔派对', '194370': '幻塔',
}


# ============================================================
# MAC 签名生成 (hmac-sha-1)
# ============================================================

def generate_mac_auth(method, path, host=API_HOST):
    """
    生成 MAC Authorization 头

    HTTP MAC 签名格式 (draft-ietf-oauth-v2-http-mac-01):
      norm-string = ts + "\n" + nonce + "\n" + method + "\n" +
                    path + "\n" + host + "\n" + port + "\n" +
                    "" + "\n" + ""

    服务器实际接受的格式可能略有不同，这里尝试标准格式
    """
    ts = str(int(time.time()))
    nonce = ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(8))

    # 构建待签名字符串
    # 标准 HTTP MAC: ts\nnonce\nmethod\nrequest-uri\nhost\nport\next\n
    # 提取 path+query
    parsed = urllib.parse.urlparse(path)
    request_uri = parsed.path
    if parsed.query:
        request_uri += "?" + parsed.query

    port = "443"

    # 标准 HTTP MAC 签名格式
    norm_string = f"{ts}\n{nonce}\n{method}\n{request_uri}\n{host}\n{port}\n\n"

    # HMAC-SHA-1
    mac_algorithm = MAC_ALGORITHM.replace("hmac-", "")  # "sha-1" -> "sha1"
    if mac_algorithm == "sha-1":
        mac_algorithm = "sha1"

    signature = base64.b64encode(
        hmac.new(
            MAC_KEY.encode('utf-8'),
            norm_string.encode('utf-8'),
            hashlib.sha1
        ).digest()
    ).decode('utf-8')

    auth = f'MAC id="{KID}",ts="{ts}",nonce="{nonce}",mac="{signature}"'
    return auth


def api_request(method, path, params=None):
    """通过 MAC 签名直接调用 API"""
    if params:
        query_str = "&".join(f"{k}={urllib.parse.quote(str(v), safe='')}"
                             for k, v in params.items())
        full_path = f"{path}?{query_str}"
        full_url = f"https://{API_HOST}{full_path}"
    else:
        full_path = path
        full_url = f"https://{API_HOST}{path}"

    auth = generate_mac_auth(method, full_path)

    headers = {
        "Host": API_HOST,
        "Accept": "application/json",
        "User-Agent": "TapTap/2026.5.19-rel.5 (Build 2026051905/1d8a57a6) TapPC-Main/2026.5.19-rel.5",
        "Authorization": auth,
    }

    # 直接使用已构造好的 URL，不再通过 params 参数
    resp = requests.get(full_url, headers=headers, timeout=15)
    return resp


# ============================================================
# 在线人数查询
# ============================================================

def get_online_quick(game_id):
    """快速查询（只看 total 字段）"""
    params = {
        "app_id": game_id,
        "from": "0",
        "limit": "1",
        "X-UA": X_UA,  # 不预编码，由 api_request 处理
    }

    resp = api_request("GET", "/group/v1/online-players", params)
    if resp and resp.status_code == 200:
        data = resp.json()
        total = data.get("data", {}).get("total", 0)
        return total
    return None


def get_online_full(game_id):
    """顺序翻页获取精确在线总数（跟随 next_page 链）"""
    x_ua_enc = urllib.parse.quote(X_UA, safe='')
    current_path = f"/group/v1/online-players?app_id={game_id}&from=0&limit=50&X-UA={x_ua_enc}"

    total = 0
    page = 0

    REQUEST_DELAY = 0.5  # 请求间隔，避免触发 API 限流

    print("  翻页计数中...", end="", flush=True)
    while current_path and page < 2000:
        page += 1
        resp = api_request("GET", current_path)
        if not resp or resp.status_code != 200:
            break

        data = resp.json()
        lst = data.get("data", {}).get("list", [])
        next_url = data.get("data", {}).get("next_page", "")

        if not lst:
            break

        total += len(lst)

        if not next_url:
            break

        # 跟随 next_page，并补充 X-UA
        next_path = next_url.replace(f"https://{API_HOST}", "")
        current_path = f"{next_path}&X-UA={x_ua_enc}"

        # 页间延迟，避免 405 限流
        time.sleep(REQUEST_DELAY)

        if page % 30 == 0:
            print(f" {total}...", end="", flush=True)

    print(f" 完成 ({page} 页)")
    return total


# ============================================================
# 主程序
# ============================================================

def main():
    if not KID or not MAC_KEY:
        print("错误: 未配置 TAPTAP_KID 和 TAPTAP_MAC_KEY")
        print("请设置环境变量或编辑脚本填入凭证")
        sys.exit(1)

    args = sys.argv[1:]
    full_mode = '--full' in args or '-f' in args
    args = [a for a in args if not a.startswith('--') and not a.startswith('-')]

    if args:
        game_id = args[0]
    else:
        print("已知游戏:")
        for gid, name in sorted(KNOWN_GAMES.items(), key=lambda x: int(x[0])):
            print(f"  {gid}: {name}")
        game_id = input("\n输入游戏 ID: ").strip()

    game_name = KNOWN_GAMES.get(game_id, f"ID={game_id}")

    print(f"查询: {game_name} (ID={game_id})")
    print()

    # 测试认证
    quick = get_online_quick(game_id)
    if quick is None:
        print("认证失败! 请检查 KID 和 MAC_KEY 是否正确")
        print(f"KID: {KID}")
        print(f"MAC_KEY: {MAC_KEY}")
        sys.exit(1)

    if full_mode:
        total = get_online_full(game_id)
        print(f"\n{game_name} 真实在线人数: {total:,} 人")
    else:
        print(f"{game_name} 在线人数: {quick}")
        if quick >= 100:
            print("(使用 --full 翻页获取精确总数)")


if __name__ == "__main__":
    main()
