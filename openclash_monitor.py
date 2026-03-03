# -*- coding: utf-8 -*-
"""
OpenClash 网络质量监控 + 自动切换最优节点
支持多台路由器，每5分钟运行一次
"""
import json, urllib2, time, sys, os, datetime
reload(sys)
sys.setdefaultencoding('utf-8')

# ====== 路由器配置 ======
ROUTERS = [
    {
        'name': '路由器1 (192.168.3.1)',
        'base': 'http://192.168.3.1',
        'api_token': 'NbAc1bNm',
        'proxy_auth': 'Clash:dCDKy0ze',
        'proxy_port': 7890,
        'config': 'Nexitally_1.yaml',
        # 策略组配置: 组名 -> (测速目标, 地区前缀列表)
        'groups': {
            u'Google':   ('http://ip-api.com/json', [u'\U0001f1fa\U0001f1f8 USA']),
            u'AI':       ('http://ip-api.com/json', [u'\U0001f1ef\U0001f1f5 Japan']),
            u'Telegram': ('http://ip-api.com/json', [u'\U0001f1f8\U0001f1ec Singapore']),
            u'Proxies':  ('http://ip-api.com/json', [u'\U0001f1ed\U0001f1f0 Hong Kong']),
            u'Netflix':  ('http://ip-api.com/json', [u'\U0001f1ed\U0001f1f0 Hong Kong']),
        },
        # 延迟阈值（ms），超过则触发切换
        'threshold': 300,
    },
    {
        'name': '路由器2 (192.168.4.1)',
        'base': 'http://192.168.4.1',
        'api_token': 'gcbqxdIG',
        'proxy_auth': 'Clash:EGM7yxxT',
        'proxy_port': 7890,
        'config': 'Nexitally_2.yaml',
        'groups': {
            u'Google':   ('http://ip-api.com/json', [u'\U0001f1fa\U0001f1f8 USA']),
            u'AI':       ('http://ip-api.com/json', [u'\U0001f1ef\U0001f1f5 Japan']),
            u'Telegram': ('http://ip-api.com/json', [u'\U0001f1f8\U0001f1ec Singapore']),
            u'Proxies':  ('http://ip-api.com/json', [u'\U0001f1ed\U0001f1f0 Hong Kong']),
            u'YouTube':  ('http://ip-api.com/json', [u'\U0001f1ed\U0001f1f0 Hong Kong']),
        },
        'threshold': 300,
    },
]

FINAL_GROUP = u'\u2708\ufe0fFinal'
LOG_FILE = '/tmp/openclash_monitor.log'
MAX_MEASURE_NODES = 15  # 最多测多少个同地区节点


def log(msg):
    ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = '[%s] %s' % (ts, msg)
    print(line)
    try:
        with open(LOG_FILE, 'a') as f:
            f.write(line + '\n')
        # 只保留最近500行
        with open(LOG_FILE, 'r') as f:
            lines = f.readlines()
        if len(lines) > 500:
            with open(LOG_FILE, 'w') as f:
                f.writelines(lines[-500:])
    except:
        pass


def get_ubus_session(base):
    req = urllib2.Request(base + '/ubus/')
    req.add_header('Content-Type', 'application/json')
    req.add_data(json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "call",
        "params": ["00000000000000000000000000000000", "session", "login",
                   {"username": "root", "password": "root"}]
    }))
    resp = json.loads(urllib2.urlopen(req, timeout=10).read())
    return resp['result'][1]['ubus_rpc_session']


def clash_get_proxy(base, token, name):
    n = name.encode('utf-8') if isinstance(name, unicode) else name
    req = urllib2.Request(base + ':9090/proxies/' + urllib2.quote(n))
    req.add_header('Authorization', 'Bearer ' + token)
    return json.loads(urllib2.urlopen(req, timeout=8).read())


def clash_switch(base, token, group, node):
    g = group.encode('utf-8') if isinstance(group, unicode) else group
    body = json.dumps({'name': node.encode('utf-8') if isinstance(node, unicode) else node})
    req = urllib2.Request(base + ':9090/proxies/' + urllib2.quote(g))
    req.add_header('Authorization', 'Bearer ' + token)
    req.add_header('Content-Type', 'application/json')
    req.add_data(body)
    req.get_method = lambda: 'PUT'
    try:
        return urllib2.urlopen(req, timeout=5).getcode()
    except Exception as e:
        return str(e)


def measure_latency(base, session, proxy_auth, proxy_port):
    """通过路由器本机 curl 测延迟，走 Final 策略"""
    req = urllib2.Request(base + '/ubus/')
    req.add_header('Content-Type', 'application/json')
    req.add_data(json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "call",
        "params": [session, "file", "exec", {
            "command": "/usr/bin/curl",
            "params": [
                "-s", "-o", "/dev/null", "-w", "TIME:%{time_total}",
                "--max-time", "8",
                "-x", "http://%s@127.0.0.1:%d" % (proxy_auth, proxy_port),
                "http://ip-api.com/json"
            ]
        }]
    }))
    try:
        resp = json.loads(urllib2.urlopen(req, timeout=15).read())
        r = resp.get('result', [])
        if len(r) > 1 and isinstance(r[1], dict):
            out = r[1].get('stdout', '')
            if 'TIME:' in out:
                return int(float(out.split('TIME:')[1]) * 1000)
    except:
        pass
    return 9999


def find_best_node(base, token, session, proxy_auth, proxy_port, group_name, prefixes):
    """找出指定策略组中延迟最低的同地区节点"""
    try:
        data = clash_get_proxy(base, token, group_name)
        all_nodes = data.get('all', [])
    except Exception as e:
        log('  获取节点列表失败: %s' % str(e))
        return None, 9999

    # 过滤同地区节点
    candidates = []
    for n in all_nodes:
        n_str = n.encode('utf-8') if isinstance(n, unicode) else n
        for prefix in prefixes:
            p = prefix.encode('utf-8') if isinstance(prefix, unicode) else prefix
            if n_str.startswith(p):
                candidates.append(n)
                break

    if not candidates:
        return None, 9999

    # 限制数量，优先测 Premium 节点
    premium = [n for n in candidates if '[Premium]' in (n.encode('utf-8') if isinstance(n, unicode) else n)]
    regular = [n for n in candidates if n not in premium]
    ordered = premium + regular
    ordered = ordered[:MAX_MEASURE_NODES]

    best_ms = 9999
    best_node = None

    for node in ordered:
        clash_switch(base, token, FINAL_GROUP, node)
        time.sleep(0.6)
        ms = measure_latency(base, session, proxy_auth, proxy_port)
        node_str = node.encode('utf-8') if isinstance(node, unicode) else node
        log('    测速: %-40s %s' % (node_str, '%dms' % ms if ms != 9999 else 'timeout'))
        if ms < best_ms:
            best_ms = ms
            best_node = node

    # 恢复 Final -> Proxies
    clash_switch(base, token, FINAL_GROUP, u'Proxies')
    return best_node, best_ms


def check_router(router):
    name = router['name']
    base = router['base']
    token = router['api_token']
    proxy_auth = router['proxy_auth']
    proxy_port = router['proxy_port']
    threshold = router['threshold']

    log('=' * 60)
    log('检查: %s' % name)

    try:
        session = get_ubus_session(base)
    except Exception as e:
        log('  连接失败: %s' % str(e))
        return

    for group_name, (test_url, prefixes) in router['groups'].items():
        try:
            proxy_data = clash_get_proxy(base, token, group_name)
            current_node = proxy_data.get('now', '?')
            current_str = current_node.encode('utf-8') if isinstance(current_node, unicode) else current_node
        except Exception as e:
            log('  [%s] 获取当前节点失败: %s' % (group_name, str(e)))
            continue

        log('  [%s] 当前节点: %s' % (group_name, current_str))

        # 切 Final 到当前节点，测延迟
        clash_switch(base, token, FINAL_GROUP, current_node)
        time.sleep(0.6)
        ms = measure_latency(base, session, proxy_auth, proxy_port)
        log('  [%s] 当前延迟: %s' % (group_name, '%dms' % ms if ms != 9999 else 'timeout'))

        # 恢复 Final
        clash_switch(base, token, FINAL_GROUP, u'Proxies')

        if ms > threshold:
            log('  [%s] ⚠️  延迟 %dms 超过阈值 %dms，开始寻找最优节点...' % (group_name, ms, threshold))
            best_node, best_ms = find_best_node(
                base, token, session, proxy_auth, proxy_port, group_name, prefixes
            )
            if best_node:
                best_str = best_node.encode('utf-8') if isinstance(best_node, unicode) else best_node
                if best_ms < threshold:
                    clash_switch(base, token, group_name, best_node)
                    log('  [%s] ✅ 已切换到: %s (%dms，低于阈值)' % (group_name, best_str, best_ms))
                elif best_ms < ms:
                    clash_switch(base, token, group_name, best_node)
                    log('  [%s] ⚡ 无节点低于 %dms，已切换到最优: %s (%dms)' % (group_name, threshold, best_str, best_ms))
                else:
                    log('  [%s] ❌ 当前节点已是最优 (%dms)，无需切换' % (group_name, ms))
            else:
                log('  [%s] ❌ 未找到可用节点' % group_name)
        else:
            log('  [%s] ✅ 延迟正常 (%dms)' % (group_name, ms))

    log('检查完成: %s' % name)


def main():
    log('OpenClash 网络质量监控启动')
    for router in ROUTERS:
        try:
            check_router(router)
        except Exception as e:
            log('路由器检查异常 %s: %s' % (router['name'], str(e)))
    log('本轮检查完毕')


if __name__ == '__main__':
    main()
