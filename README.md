# TapTap Chain Tracker

TapTap 游戏在线人数链式翻页追踪器。

## 用法

```bash
pip install requests
python tracker_chain.py                       # 抓取所有游戏
python tracker_chain.py --games 714123,172664 # 指定游戏
python tracker_chain.py --html-only           # 仅生成 HTML
python tracker_chain.py --delay 1.0           # 自定义请求间隔
```

## 输出

- `online_chain.csv` — 历史数据
- `online_chain.html` — 可视化图表
- `scan_logs/` — 每次扫描的玩家详情日志

## 环境变量

| 变量 | 说明 |
|------|------|
| `TAPTAP_KID` | MAC 认证 KID |
| `TAPTAP_MAC_KEY` | MAC 认证密钥 |
