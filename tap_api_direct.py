#!/usr/bin/env python3
"""
TapTap 在线人数查询 — 直接 API 调用（无需 TapTap 客户端）
使用 X-Tap-Sign 签名 (HMAC-SHA256)，可在 Linux VPS 部署

用法:
  python tap_api_direct.py 714119
"""

import requests
import urllib.parse
import time
import base64
import hmac
import hashlib
import random
import uuid
import json
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ============================================================
# 签名配置 (来自 APK 逆向 b.java)
# ============================================================
CLIENT_SECRET = "aOqilgPqN4grnMG5VdLlhLptAU3WHorK"

CONFIG = {
    "host": "api.taptapdada.com",
    "user_agent": (
        "TapTap/2.96.0-rel#100200 (com.taptap; build:296001002; Android 11) "
        "Okhttp/3.12.1"
    ),
}

# ============================================================
# 签名生成 (与 tapsearch.py 相同)
# ============================================================

def build_x_ua():
    date_str = time.strftime("%Y%m%d")
    rnd = ''.join(random.choice(
        'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
    ) for _ in range(12))
    ch = f"organic-direct_index_d{date_str}--{date_str[2:]}{rnd}"
    uid = str(uuid.uuid4())
    return (
        f"V=1&PN=TapTap&VN=2.96.0-rel.100200&VN_CODE=296001002"
        f"&LOC=CN&LANG=zh_CN&CH={ch}&UID={uid}"
        f"&NT=1&SR=1080x2220&DEB=Xiaomi&DEM=Redmi+Note+8+Pro&OSV=11"
    )


def compute_x_tap_sign(method, url_path, query, x_tap_headers, body_bytes):
    x_tap = [(k.lower(), v) for k, v in x_tap_headers.items()
             if k.lower().startswith('x-tap-')]
    x_tap.sort(key=lambda kv: kv[0])
    sorted_headers_str = "\n".join(f"{k}:{v}" for k, v in x_tap)

    path_query = f"{url_path}?{query}"
    signing_str = f"{method}\n{path_query}\n{sorted_headers_str}\n"
    signing_bytes = signing_str.encode('utf-8') + body_bytes + b"\n"

    return base64.b64encode(
        hmac.new(CLIENT_SECRET.encode('utf-8'), signing_bytes, hashlib.sha256).digest()
    ).decode('utf-8')


def make_api_request(method, url_path, query_params, body=b"",
                     content_type="application/x-protobuf",
                     accept="application/x-protobuf"):
    """通用 TapTap API 请求"""
    x_ua = build_x_ua()
    query = "&".join(f"{k}={urllib.parse.quote(str(v), safe='')}"
                     for k, v in query_params.items())
    query += f"&X-ENC=pb&X-UA={urllib.parse.quote(x_ua, safe='')}"

    ts_str = f"{int(time.time()):010d}"
    nonce = ''.join(random.choice('abcdefghijklmnopqrstuvwxyz0123456789')
                    for _ in range(20))

    x_tap_headers = {"X-Tap-Nonce": nonce, "X-Tap-Ts": ts_str}
    x_tap_sign = compute_x_tap_sign(method, url_path, query, x_tap_headers, body)

    headers = {
        "Host": CONFIG["host"],
        "Accept": accept,
        "User-Agent": CONFIG["user_agent"],
        "Content-Type": content_type,
        "Content-Length": str(len(body)),
        "Accept-Encoding": "gzip",
        "Connection": "Keep-Alive",
        "X-Tap-Sign": x_tap_sign,
        "X-Tap-Nonce": nonce,
        "X-Tap-Ts": ts_str,
    }

    url = f"https://{CONFIG['host']}{url_path}?{query}"
    resp = requests.post(url, data=body, headers=headers, timeout=15)
    return resp


def make_json_request(url_path, query_params):
    """JSON API 请求（不需要签名，使用 Web X-UA）"""
    x_ua = "V=1&PN=WebApp&LANG=zh_CN&VN_CODE=102&LOC=CN&PLT=PC&DS=Android&UID=d52ddf3e-6028-4fa4-ba5a-56d8a7bb4729&OS=Windows&OSV=10&DT=PC"
    query_params["X-UA"] = x_ua

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
        "Accept": "application/json",
    }

    url = f"https://{CONFIG['host']}{url_path}"
    resp = requests.get(url, params=query_params, headers=headers, timeout=15)
    return resp


def get_online_count_json(game_id):
    """方案 A: JSON API（不需要签名）"""
    resp = make_json_request("/app/v3/detail", {
        "id": game_id,
        "Identifier": f"auto_{game_id}",
    })
    if resp.status_code == 200:
        data = resp.json()
        stat = data.get("data", {}).get("app", {}).get("stat", {})
        return {
            "play_total": stat.get("play_total", 0),
            "fans_count": stat.get("fans_count", 0),
            "reserve_count": stat.get("reserve_count", 0),
            "pc_download_count": stat.get("pc_download_count", 0),
            "hits_total": stat.get("hits_total", 0),
            "review_count": stat.get("review_count", 0),
        }
    return None


def get_online_count_proto(game_id):
    """方案 B: 尝试 Protobuf API 获取 user_playing_count"""
    def encode_varint(v):
        buf = bytearray()
        while v > 127:
            buf.append((v & 0x7F) | 0x80)
            v >>= 7
        buf.append(v & 0x7F)
        return bytes(buf)

    def uv(tag, v):
        return encode_varint((tag << 3) | 0) + encode_varint(v)

    def us(tag, s):
        data = s.encode('utf-8')
        return encode_varint((tag << 3) | 2) + encode_varint(len(data)) + data

    def read_varint(data, offset):
        value, shift = 0, 0
        while offset < len(data):
            byte = data[offset]; value |= (byte & 0x7F) << shift; offset += 1
            if not (byte & 0x80): break
            shift += 7
        return value, offset

    def read_ld(data, offset):
        length, offset = read_varint(data, offset)
        return data[offset:offset + length], offset + length

    # 尝试多个 protobuf 端点
    endpoints = [
        # 搜索 API (已验证可用)
        "/search/v6/agg-search",
        # 可能的详情端点
        "/app/v3/detail",
        "/v1/detail-by-id",
    ]

    for path in endpoints:
        if path == "/search/v6/agg-search":
            body = (us(2, "mix") + us(3, str(game_id)) +
                    us(5, "suggest") + uv(7, 10))
            msg_type = "apis.clientapi.search.AggSearchV6Request"
        else:
            body = uv(1, game_id) + us(2, f"auto_{game_id}")
            msg_type = "apis.clientapi.app.DetailV3Request"

        ct = (f'application/x-protobuf; '
              f'desc="https://pbdesc.xdrnd.cn/apis.desc"; '
              f'messageType="{msg_type}"')

        try:
            resp = make_api_request("POST", path, {}, body, content_type=ct)

            if resp.status_code == 200 and len(resp.content) > 100:
                # 搜索 user_playing_count (field 20)
                found = {}
                off = 0
                data = resp.content
                while off < len(data):
                    try:
                        tw, off = read_varint(data, off)
                        wt, t = tw & 7, tw >> 3
                        if wt == 0:
                            v, off = read_varint(data, off)
                            if t == 20:
                                found['user_playing_count'] = v
                            elif t == 19:
                                found['user_played_count'] = v
                            elif t == 18:
                                found['user_want_count'] = v
                            elif t == 5:
                                found['play_total'] = v
                        elif wt == 2:
                            r, off = read_ld(data, off)
                        elif wt == 1: off += 8
                        elif wt == 5: off += 4
                    except:
                        break
                return found, path
        except Exception as e:
            pass

    return None, None


# ============================================================
# 主程序
# ============================================================

def main():
    game_id = sys.argv[1] if len(sys.argv) > 1 else "714119"

    print("=" * 60)
    print(f"  TapTap 在线人数 — 直接 API（无需客户端）")
    print(f"  游戏 ID: {game_id}")
    print("=" * 60)
    print()

    # 方案 A: JSON API (不需要签名，始终可用)
    print("[A] JSON API (无签名，通用)...")
    json_data = get_online_count_json(game_id)
    if json_data:
        print(f"  play_total:       {json_data['play_total']:,}")
        print(f"  fans_count:       {json_data['fans_count']:,}")
        print(f"  reserve_count:    {json_data['reserve_count']:,}")
        print(f"  pc_download_count:{json_data['pc_download_count']:,}")
        print(f"  hits_total:       {json_data['hits_total']:,}")
        print(f"  review_count:     {json_data['review_count']:,}")
    else:
        print("  失败")

    # 方案 B: Protobuf API (需要签名)
    print()
    print("[B] Protobuf API (X-Tap-Sign 签名)...")
    proto_data, used_path = get_online_count_proto(game_id)
    if proto_data:
        print(f"  端点: {used_path}")
        for k, v in sorted(proto_data.items()):
            print(f"  {k}: {v:,}" if v > 0 else f"  {k}: {v}")
        if proto_data.get('user_playing_count', 0) > 0:
            print(f"\n  ★ 当前在线人数: {proto_data['user_playing_count']:,}")
    else:
        print("  user_playing_count 未在 protobuf 响应中找到")
        print("  (该字段仅在原生 protobuf API 中暴露，JSON API 因 omitempty 会省略零值)")

    print()
    print("=" * 60)
    print("VPS 部署说明:")
    print("  方案 A (JSON API) — 无需任何认证，可直接部署")
    print("  方案 B (Protobuf API) — 需要 X-Tap-Sign 签名，")
    print("    签名算法已内置，可独立运行于任意 Linux VPS")
    print("=" * 60)


if __name__ == "__main__":
    main()
