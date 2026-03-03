# OpenClash Config Tools

一套用于管理 OpenClash 软路由的自动化工具，包括：

- 📊 **节点网络质量监控** - 实时测速，自动切换低延迟节点
- ⏰ **定时任务** - 每5分钟自动检测，延迟超过阈值自动换节点
- 🔀 **多 YAML 合并** - 将多个订阅配置合并为一个，去重节点并更新策略组

## 文件说明

```
openclash_monitor.py     # 核心监控脚本（测速 + 自动切换）
merge_and_upload.py      # 多 YAML 合并脚本
download_yamls_hex.py    # 从路由器下载 YAML（hexdump 方式，支持大文件）
```

## 环境要求

- 跳板机（群晖 NAS 等）：Python 2.7
- 路由器：OpenWrt + OpenClash（Clash Meta 内核）
- 跳板机可通过 HTTP 访问路由器 192.168.3.1 和 192.168.4.1

## 配置说明

### openclash_monitor.py

编辑 `ROUTERS` 列表，填入路由器信息：

```python
ROUTERS = [
    {
        'name': '路由器1 (192.168.3.1)',
        'base': 'http://192.168.3.1',
        'api_token': 'your_clash_api_token',
        'proxy_auth': 'Clash:your_proxy_password',
        'proxy_port': 7890,
        'groups': {
            'Google':   ('http://ip-api.com/json', ['🇺🇸 USA']),
            'AI':       ('http://ip-api.com/json', ['🇯🇵 Japan']),
            'Telegram': ('http://ip-api.com/json', ['🇸🇬 Singapore']),
            'Proxies':  ('http://ip-api.com/json', ['🇭🇰 Hong Kong']),
        },
        'threshold': 300,   # 延迟超过此值(ms)触发切换
    },
]
```

### 运行方式

```bash
# 手动运行
python2 openclash_monitor.py

# 配合 OpenClaw cron 每5分钟自动运行（见 cron 配置）
```

## 工作原理

1. 通过路由器 ubus API 登录并执行命令
2. 切换 `✈️Final` 策略组到目标节点
3. 在路由器本机发起 curl 测速（经过 Clash 代理）
4. 延迟超过阈值时扫描同地区所有节点，切换到最优
5. 无节点低于阈值时，切换到延迟最低的（保证始终用最优）

## 日志

运行日志写入路由器 `/tmp/openclash_monitor.log`（最多保留500行）。
