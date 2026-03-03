# OpenClash Config Tools - 使用说明

## 快速开始

### 1. 节点监控与自动切换

```bash
# 上传脚本到跳板机
scp openclash_monitor.py user@jumphost:/path/to/scripts/

# 手动运行一次
ssh user@jumphost 'python2 /path/to/scripts/openclash_monitor.py'

# 查看日志
ssh user@jumphost 'cat /tmp/openclash_monitor.log'  # 路由器上的日志
```

### 2. 合并多个 YAML 订阅

```bash
# 先下载路由器上的 yaml 文件
python2 download_yamls_hex.py

# 再合并（以 Nexitally_1.yaml 为原型）
python2 merge_and_upload.py
```

## 关键参数

### Clash API

- 端口：9090（默认）
- 鉴权：`Authorization: Bearer <api_token>`
- 代理端口：7890（HTTP），7891（SOCKS5）

### ubus 执行命令

通过路由器 ubus HTTP API 执行命令，无需 SSH：

```python
# 登录获取 session
curl http://192.168.3.1/ubus/ -d '{"method":"call","params":["0000...","session","login",{"username":"root","password":"root"}]}'

# 执行命令
curl http://192.168.3.1/ubus/ -d '{"method":"call","params":["SESSION","file","exec",{"command":"/bin/cmd","params":["arg1"]}}]}'
```

### 策略组切换

```bash
curl -X PUT http://192.168.3.1:9090/proxies/GroupName \
  -H 'Authorization: Bearer TOKEN' \
  -d '{"name": "NodeName"}'
```

## 监控阈值说明

| 延迟 | 处理方式 |
|------|---------|
| ≤ 300ms | 正常，不切换 |
| > 300ms，有节点 < 300ms | 切换到最快的 |
| > 300ms，无节点 < 300ms | 切换到延迟最低的 |

## 注意事项

1. 测速时会临时切换 `✈️Final` 策略组，测速结束后自动恢复
2. 监控脚本每次运行约需 30-60 秒（取决于需要切换的组数）
3. 两台路由器串行检测，互不影响
