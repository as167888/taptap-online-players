# TapTap 游戏在线人数查询

通过逆向 TapTap PC 客户端 API，实现无需客户端即可查询任意游戏在 TapTap 平台上的实时在线玩家数量。

## 功能

- 查询指定游戏的精确在线人数（逐页翻到底）
- 批量查询多款游戏在线人数排行
- 查询游戏详情（评分、粉丝、下载、预约、开发商等 42 个字段）
- 支持 VPS/Linux 独立部署，无需 Windows 客户端
- 支持 Windows 本地 Pipe 方案（自动认证，无需配置密钥）

## 快速开始

### 1. 安装依赖

```bash
pip install requests
```

### 2. 配置凭证

```bash
export TAPTAP_KID="your_kid"
export TAPTAP_MAC_KEY="your_mac_key"
```

### 3. 查询

```bash
# 单游戏快速查询（展示值）
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

- 返回玩家列表（昵称、游玩时长、当前游戏）
- `total` 字段恒为 100（展示上限），需跟随 `next_page` 翻页到底获取真实总数
- 需要 MAC 认证，或通过 Pipe 免签名

### 游戏详情（JSON API，无需认证）

```
GET /app/v3/detail?id={game_id}&Identifier={package_name}
Host: api.taptapdada.com
```

返回完整的游戏信息，共 42 个字段：

#### 基础信息

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | int | 游戏 ID |
| `title` | string | 游戏名称 |
| `identifier` | string | 包名 |
| `itunes_id` | string | App Store ID |
| `style` | int | 样式标识 |
| `tags` | list | 标签列表 (id, value, uri, web_url) |
| `hints` | list | 提示标签（如"开放世界RPG"） |
| `title_labels` | list | 标题标签 |

#### 开发者与状态

| 字段 | 类型 | 说明 |
|------|------|------|
| `developers` | list | 开发商信息 (id, name, website, is_online, label) |
| `has_official` | bool | 是否有官方内容 |
| `has_moment_rec` | bool | 是否有动态推荐 |
| `is_deny_minors` | bool | 是否限制未成年 |
| `hidden_button` | bool | 是否隐藏按钮 |

#### 媒体资源

| 字段 | 类型 | 说明 |
|------|------|------|
| `icon` | dict | 图标（url, medium_url, small_url, large_url, original_url, width, height, color） |
| `banner` | dict | 封面横幅（同上多尺寸） |
| `screenshots` | list | 截图列表（每项含多尺寸 URL） |
| `videos` | list | 宣传视频（video_id, play_url 含 m3u8, thumbnail, 时长） |
| `awards` | list | 获奖记录 (id, title, subtitle, icon, year, award_platform) |

#### 内容

| 字段 | 类型 | 说明 |
|------|------|------|
| `description` | dict | 游戏简介 (text) |
| `developer_note` | dict | 开发者的话 (text) |
| `whatsnew` | dict | 最新更新内容 (text) |
| `information` | list | 信息栏（type, title, text, link） |
| `seo` | dict | SEO 信息 (price, currency, index) |
| `sharing` | dict | 分享信息 (url, title, description, image) |

#### 统计 (stat)

| 字段 | 说明 |
|------|------|
| `rating` | 评分详情 (score, max, latest_score, latest_version_score, latest_review_count, latest_version_review_count) |
| `vote_info` | 投票分布 (1-5 星各多少票) |
| `review_tags` | 评价标签映射 |
| `hits_total` | 点击量 |
| `hits_total_val` | 点击量（另一个维度） |
| `play_total` | 总游玩次数 |
| `bought_count` | 购买/下载量 |
| `feed_count` | Feed 动态数 |
| `reserve_count` | 预约数 |
| `fans_count` | 粉丝数 |
| `review_count` | 评价总数 |
| `topic_count` | 话题数 |
| `video_count` | 视频数 |
| `album_count` | 相册数 |
| `wish_count` | 愿望单 |
| `pc_download_count` | PC 下载量 |
| `pc_sale_count` | PC 销量 |
| `level_like_count` | 等级点赞 |
| `recent_sandbox_played_count` | 最近沙盒游玩 |
| `official_topic_count` | 官方话题数 |
| `official_video_count` | 官方视频数 |
| `official_album_count` | 官方相册数 |

#### 下载与价格

| 字段 | 类型 | 说明 |
|------|------|------|
| `download` | dict | APK 信息 (apk_id, apk 含 name/size/md5/version, permissions) |
| `price` | dict | 价格 (taptap_current, discount_rate) |
| `uri` | dict | 下载链接 (google, google_play, apple, download_site) |
| `button_flag` | int | 按钮状态标记 |
| `button_params` | dict | 按钮参数 |
| `can_buy_redeem_code` | dict | 是否可购买兑换码 |
| `serial_number` | dict | 序列号/激活码信息 |

#### 其他

| 字段 | 类型 | 说明 |
|------|------|------|
| `update_date` | string | 更新日期 |
| `event_log` | dict | 埋点参数 (paramId, paramType) |
| `log` | dict | 7 种操作的埋点配置 (follow, open, page_view, play, reserve, unfollow, unreserved) |
| `show_module` | list | 展示模块开关 (key, value) |
| `complaint` | dict | 投诉举报链接 |
| `downgrade_request` | list | 降级请求参数 |
| `highlight_tags` | list | 高亮标签 |
| `console_game_download_url` | list | 主机游戏下载链接 |
| `console_game_supported_system` | list | 主机游戏支持平台 |
| `is_console_game` | bool | 是否主机游戏 |

## 认证机制

### MAC 签名（PC 客户端 API）

```
norm_string = ts + "\n" + nonce + "\n" + GET + "\n" + path?query + "\n" + host + "\n" + 443 + "\n" + "\n"
Authorization: MAC id="{kid}",ts="{ts}",nonce="{nonce}",mac="{base64(hmac-sha1(mac_key, norm_string))}"
```

- `kid` 和 `mac_key` 来源：TapTap 客户端登录后存储在 `config.taptap`（AES-256-CBC 加密，密钥 `taptap`）
- 与网卡 MAC 地址无关，可跨机器部署
- `mac_algorithm`: hmac-sha-1

### X-Tap-Sign（移动端 Protobuf API）

```
signing_string = "METHOD\n/path?query\nx-tap-nonce:xxx\nx-tap-ts:xxx\n" + body + "\n"
X-Tap-Sign = base64(HMAC-SHA256(client_secret, signing_string))
```

- `client_secret` 从 APK `resources.arsc` 解密获取

### JSON API（无需认证）

`/app/v3/detail` 等端点无需认证头，直接 GET 即可访问游戏基本信息。

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

| 游戏 | ID | 包名 | 评分 | 粉丝 |
|------|-----|------|------|------|
| 异环 | 714119 | com.hottagames.yh.laohu | 7.0 | 833万 |
| 火炬之光：无限 | 172664 | com.xindong.torchlight | 7.3 | 365万 |
| 洛克王国：世界 | 188212 | com.tencent.nrc | 5.0 | 979万 |
| 鸣潮 | 234280 | com.kurogame.mingchao | 7.2 | 1,274万 |
| 心动小镇 | 45213 | com.xd.xdt | 8.8 | 3,778万 |
| 原神 | 168332 | com.miHoYo.Yuanshen | 7.9 | 3,779万 |
| 超自然行动组 | 714123 | com.pi.czrxdfirst | 6.8 | 1,113万 |
| 明日方舟：终末地 | 232326 | com.hypergryph.endfield | 5.7 | 660万 |
| 和平精英 | 70056 | com.tencent.tmgp.pubgmhd | 7.1 | 8,101万 |
| 三角洲行动 | 330259 | com.tencent.tmgp.dfm | 5.3 | 3,011万 |
| 伊瑟 | 236627 | com.xd.etheria | 7.6 | 260万 |
| 明日方舟 | 70253 | com.hypergryph.arknights | 8.1 | 1,219万 |
| 崩坏：星穹铁道 | 224267 | com.miHoYo.hkrpg | 7.5 | 1,902万 |
| 燕云十六声 | 239372 | com.netease.yyslscn | 7.0 | 978万 |
| 绝区零 | 234493 | com.miHoYo.Nap | 6.7 | 1,352万 |
| 幻塔 | 192675 | com.pwrd.hotta.laohu | 5.4 | 440万 |

## 注意事项

- **请求频率**：API 有严格的限流机制，建议每次请求间隔 ≥ 0.5 秒，否则 IP 会被阿里云 WAF 封禁约 30-60 分钟
- **Pipe 绕过**：WAF 封禁仅影响直连，TapTap 客户端 Go 后端走不同通道，Pipe 方案不受影响
- **数据含义**：在线人数 = 通过 TapTap 启动器游玩的用户数，不等于游戏总在线人数
- **`total: 100`**：在线玩家 API 返回的 `total` 为展示上限，真实值需翻页到底
- **`user_playing_count`**：仅在 Protobuf API 中暴露，JSON API 因 `omitempty` 省略零值

## 免责声明

本项目仅供学习研究使用，请遵守 TapTap 的服务条款。不得用于商业用途或侵犯他人权益。
