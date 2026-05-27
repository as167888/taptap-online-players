# TapTap 游戏在线人数查询

通过逆向 TapTap PC 客户端 API，实现无需客户端即可查询任意游戏在 TapTap 平台上的实时在线玩家数量。

## 功能

- 查询指定游戏的精确在线人数（逐页翻到底）
- 批量查询多款游戏在线人数排行
- 支持 VPS/Linux 独立部署，无需 Windows 客户端
- 支持 Windows 本地 Pipe 方案（自动认证，无需配置密钥）

## 快速开始

### 1. 安装依赖

```bash
pip install requests
```

### 2. 配置凭证

凭证已内置在脚本中，也可通过环境变量设置：

```bash
export TAPTAP_KID="your_kid"
export TAPTAP_MAC_KEY="your_mac_key"
```

### 3. 查询

```bash
# 单游戏快速查询
python tap_vps.py 714119

# 单游戏精确总数（翻页到底）
python tap_vps.py 714119 --full

# 批量查询多款游戏
python batch_online.py
```

## API 端点

### 在线玩家列表

```
GET /group/v1/online-players?app_id={game_id}&from=0&limit=50
Host: api.taptapdada.com
Authorization: MAC id="{kid}",ts="{ts}",nonce="{nonce}",mac="{signature}"
```

返回 `total` 字段恒为 100（展示上限），需跟随 `next_page` 翻页到底获取真实总数。

### 游戏详情（JSON API，无需认证）

```
GET /app/v3/detail?id={game_id}&Identifier=...
Host: api.taptapdada.com
```

返回 `StatInfo` 含粉丝数、评分、预约量、下载量等，但不含在线人数。

## 认证机制

### MAC 签名（PC 客户端 API）

```
norm_string = ts + "\n" + nonce + "\n" + GET + "\n" + path?query + "\n" + host + "\n" + 443 + "\n" + "\n"
Authorization: MAC id="{kid}",ts="{ts}",nonce="{nonce}",mac="{base64(hmac-sha1(mac_key, norm_string))}"
```

- `kid` 和 `mac_key` 来源：TapTap 客户端登录后存储在 `config.taptap`（AES-256-CBC 加密，密钥为 `taptap`）
- 与网卡 MAC 地址无关，可跨机器部署
- `mac_algorithm`: hmac-sha-1

### X-Tap-Sign（移动端 Protobuf API）

```
signing_string = "METHOD\n/path?query\nx-tap-nonce:xxx\nx-tap-ts:xxx\n" + body + "\n"
X-Tap-Sign = base64(HMAC-SHA256(client_secret, signing_string))
```

- `client_secret` 从 APK `resources.arsc` 解密获取

## 项目结构

```
├── README.md                # 项目说明
├── tap_vps.py               # 主脚本 — VPS 独立部署版 (MAC 签名)
├── batch_online.py          # 批量查询多款游戏在线排行
├── tap_api_direct.py        # JSON API 方案 (无需认证，数据有限)
├── tap_online.py            # Pipe 方案 (需 Windows + TapTap 客户端)
├── captures/                # Burp Suite 抓包样本
│   ├── request.txt          # 请求样例
│   └── response.txt         # 响应样例
└── requirements.txt         # Python 依赖
```

## 已知游戏 ID

| 游戏 | ID | 备注 |
|------|-----|------|
| 异环 | 714119 | |
| 火炬之光：无限 | 172664 | |
| 原神 | 168332 | 自有启动器，TapTap 追踪量低 |
| 崩坏：星穹铁道 | 224267 | 自有启动器 |
| 洛克王国：世界 | 188212 | |
| 鸣潮 | 234280 | |
| 绝区零 | 314057 | |
| 和平精英 | 70056 | |
| 明日方舟 | 337799 | |
| 三角洲行动 | 330259 | |
| 心动小镇 | 45213 | |
| 明日方舟：终末地 | 232326 | |
| 超自然行动组 | 714123 | |
| 伊瑟 | 759688 | |

## 注意事项

- **请求频率**：API 有严格的限流机制，建议每次请求间隔 ≥ 0.5 秒，否则 IP 会被阿里云 WAF 封禁约 15 分钟
- **数据含义**：在线人数 = 通过 TapTap 启动器游玩的用户数，不等于游戏总在线人数
- **`total: 100`**：API 返回的 `total` 字段恒为 100（展示上限），真实值需翻页到底

## 免责声明

本项目仅供学习研究使用，请遵守 TapTap 的服务条款。不得用于商业用途或侵犯他人权益。
