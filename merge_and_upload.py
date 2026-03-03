# -*- coding: utf-8 -*-
"""
生成 mix.yaml：合并节点 + 将新节点加入对应策略组
"""
import json, urllib2, sys, os, re, binascii
reload(sys); sys.setdefaultencoding('utf-8')

BASE = 'http://192.168.3.1'
OUTDIR = '/tmp/yaml_merge2'

def get_session():
    req = urllib2.Request(BASE + '/ubus/')
    req.add_header('Content-Type', 'application/json')
    req.add_data(json.dumps({"jsonrpc":"2.0","id":1,"method":"call","params":["00000000000000000000000000000000","session","login",{"username":"root","password":"root"}]}))
    return json.loads(urllib2.urlopen(req, timeout=8).read())['result'][1]['ubus_rpc_session']

SESSION = get_session()

def ubus_exec(cmd, args, timeout=30):
    req = urllib2.Request(BASE + '/ubus/')
    req.add_header('Content-Type', 'application/json')
    req.add_data(json.dumps({"jsonrpc":"2.0","id":1,"method":"call","params":[SESSION,"file","exec",{"command":cmd,"params":args}]}))
    r = json.loads(urllib2.urlopen(req, timeout=timeout+5).read()).get('result',[])
    if len(r)>1 and isinstance(r[1],dict):
        return r[1].get('stdout',''), r[1].get('stderr','')
    return '', ''

def read_file(path):
    with open(path, 'rb') as f:
        return f.read().decode('utf-8', errors='replace')

def get_name(block):
    m = re.search(r'^-\s+name:\s*(.+)', block, re.MULTILINE)
    if m: return m.group(1).strip().strip('"\'')
    m2 = re.search(r"name:\s*'([^']+)'", block)
    if m2: return m2.group(1).strip()
    m3 = re.search(r'name:\s*"([^"]+)"', block)
    if m3: return m3.group(1).strip()
    m4 = re.search(r'name:\s*([^,}\n]+)', block)
    if m4: return m4.group(1).strip().strip('"\'')
    return None

def get_server_port(block):
    sm = re.search(r'server:\s*([^\s,}\n]+)', block)
    pm = re.search(r'\bport:\s*([^\s,}\n]+)', block)
    return (sm.group(1).strip() if sm else '', pm.group(1).strip() if pm else '')

def is_info_node(name):
    if not name: return True
    bads = [' G |', ' GB', 'Traffic', 'Expire', 'Reset', 'Days Left', 'PASS', 'REJECT',
            'dns-out', u'\u5957\u9910', u'\u5269\u4f59', u'\u6d41\u91cf', u'\u5230\u671f']
    return any(p in name for p in bads)

def extract_proxies(content):
    lines = content.splitlines()
    in_proxies = False
    proxies = []
    current = []
    for line in lines:
        if re.match(r'^proxies\s*:', line):
            in_proxies = True; continue
        if in_proxies:
            if re.match(r'^[a-zA-Z]', line) and not line.startswith('-') and not line.startswith(' '):
                if current: proxies.append('\n'.join(current)); current = []
                in_proxies = False; continue
            stripped = line.strip()
            if re.match(r'^-\s+\{?\s*name:', stripped):
                if current: proxies.append('\n'.join(current))
                current = [stripped]
            elif current:
                first = current[0].strip()
                if re.match(r'^-\s+\{', first) and first.rstrip().endswith('}'):
                    proxies.append('\n'.join(current)); current = []
                    if re.match(r'^-\s+\{?\s*name:', stripped): current = [stripped]
                else:
                    current.append(line)
    if current: proxies.append('\n'.join(current))
    return proxies

# 判断节点属于哪个地区分组（对应 Nexitally_1 的策略组名）
def get_region_groups(name):
    """返回该节点应该加入的策略组列表"""
    if not name: return []
    n = name.lower()
    groups = ['Proxies']  # 所有节点都加入 Proxies

    # 按名称匹配地区
    if any(x in n for x in ['hong kong', 'hongkong', u'\u9999\u6e2f']):
        groups.append(u'\U0001f1ed\U0001f1f0 Hong Kong')
    elif any(x in n for x in ['japan', u'\u65e5\u672c']):
        groups.append(u'\U0001f1ef\U0001f1f5 Japan')
    elif any(x in n for x in ['singapore', u'\u65b0\u52a0\u5761']):
        groups.append(u'\U0001f1f8\U0001f1ec Singapore')
    elif any(x in n for x in ['united states', 'usa', 'us ', 'angeles', 'san jose', 'seattle', u'\u7f8e\u56fd']):
        groups.append(u'\U0001f1fa\U0001f1f8 United States')
    elif any(x in n for x in ['germany', u'\u5fb7\u56fd']):
        groups.append(u'\U0001f1e9\U0001f1ea Germany')
    elif any(x in n for x in ['taiwan', u'\u53f0\u6e7e', u'\u53f0\u7063']):
        groups.append(u'\U0001f1e8\U0001f1f3 Taiwan')
    elif any(x in n for x in ['korea', u'\u97e9\u56fd']):
        groups.append(u'\U0001f1f0\U0001f1f7 Korea')
    elif any(x in n for x in ['france', u'\u6cd5\u56fd']):
        groups.append(u'\U0001f1eb\U0001f1f7 France')
    elif any(x in n for x in ['netherlands', u'\u8377\u5170']):
        groups.append(u'\U0001f1f3\U0001f1f1 Netherlands')
    elif any(x in n for x in ['united kingdom', 'uk ', u'\u82f1\u56fd']):
        groups.append(u'\U0001f1ec\U0001f1e7 United Kingdom')

    return groups

# ===== 读取并合并节点 =====
print("读取文件...")
base_content = read_file(OUTDIR + '/Nexitally_1.yaml')
base_proxies = extract_proxies(base_content)
print("Nexitally_1: %d 节点" % len(base_proxies))

seen_names = set()
seen_sp = set()
for p in base_proxies:
    n = get_name(p); sp = get_server_port(p)
    if n: seen_names.add(n)
    if sp[0]: seen_sp.add(sp)

new_proxies = []  # (block, name, groups)
for fname in ['Nexitally_2.yaml', 'Nexitally_3.yaml', 'kendeji.yaml', 'test.yaml']:
    fpath = OUTDIR + '/' + fname
    if not os.path.exists(fpath): continue
    proxies = extract_proxies(read_file(fpath))
    added = 0
    for p in proxies:
        n = get_name(p); sp = get_server_port(p)
        if is_info_node(n): continue
        if (n and n in seen_names) or (sp[0] and sp in seen_sp): continue
        block = p.strip()
        grps = get_region_groups(n if n else '')
        new_proxies.append((block, n, grps))
        if n: seen_names.add(n)
        if sp[0]: seen_sp.add(sp)
        added += 1
    print("  %s: +%d" % (fname, added))

print("新增节点: %d 个" % len(new_proxies))

# ===== 修改 proxy-groups：把新节点加入对应策略组 =====
lines = base_content.splitlines()

# 找 proxies 块结束 = proxy-groups 开始
proxy_end = len(lines)
in_proxies = False
for i, line in enumerate(lines):
    if re.match(r'^proxies\s*:', line):
        in_proxies = True; continue
    if in_proxies and re.match(r'^[a-zA-Z]', line) and not line.startswith('-'):
        proxy_end = i; break

# 找各策略组的 proxies 列表末尾，插入新节点
# 策略组格式：
# - name: GroupName
#   ...
#   proxies:
#   - node1
#   - node2       <-- 在这里末尾插入
# - name: NextGroup  <-- 或者到这里为止

# 收集所有策略组的位置
pg_start = None
for i, line in enumerate(lines):
    if re.match(r'^proxy-groups\s*:', line):
        pg_start = i; break

if pg_start is None:
    print("ERROR: proxy-groups 未找到")
    sys.exit(1)

print("proxy-groups 起始行: %d" % pg_start)

# 构建新行列表
# 先插入新 proxy 节点
new_lines = []
for line in lines[:proxy_end]:
    new_lines.append(line)
while new_lines and new_lines[-1].strip() == '':
    new_lines.pop()
for block, n, grps in new_proxies:
    new_lines.append(block)
new_lines.append('')

# proxy-groups 部分：逐行处理，在合适的位置插入节点引用
pg_lines = lines[proxy_end:]

# 建立需要插入的 {group_name: [node_names]} 映射
group_inserts = {}
for block, n, grps in new_proxies:
    if not n: continue
    for g in grps:
        if g not in group_inserts:
            group_inserts[g] = []
        group_inserts[g].append(n)

print("需要更新的策略组:", [k.encode('utf-8') if isinstance(k,unicode) else k for k in group_inserts.keys()])

# 处理 proxy-groups 部分，找每个组的 proxies 列表末尾插入
result_pg = []
i = 0
current_group_name = None
in_group_proxies = False
last_proxy_item_idx = None  # 最后一个 "  - xxx" 行的索引

while i < len(pg_lines):
    line = pg_lines[i]

    # 检测组名
    m = re.match(r'^- name:\s*(.+)', line)
    if m:
        # 在切换到新组前，如果上个组有待插入节点，在 last_proxy_item_idx 后插入
        if current_group_name and in_group_proxies and last_proxy_item_idx is not None:
            nodes_to_insert = group_inserts.get(current_group_name, [])
            if nodes_to_insert:
                insert_pos = last_proxy_item_idx + 1
                for nn in nodes_to_insert:
                    nn_yaml = '  - "%s"' % nn if any(c in nn for c in [u'\u2019', '"', "'", ':']) else '  - ' + nn
                    result_pg.insert(insert_pos, nn_yaml)
                    insert_pos += 1
                print("  -> %s: 插入 %d 个节点" % (
                    current_group_name.encode('utf-8') if isinstance(current_group_name,unicode) else current_group_name,
                    len(nodes_to_insert)))
                group_inserts[current_group_name] = []  # 已处理

        raw_name = m.group(1).strip().strip('"\'')
        current_group_name = raw_name
        in_group_proxies = False
        last_proxy_item_idx = None

    # 检测 proxies: 子段
    if re.match(r'^\s+proxies\s*:', line) and current_group_name:
        in_group_proxies = True

    # 记录 proxies 列表中最后一个节点行
    if in_group_proxies and re.match(r'^\s+- ', line) and not re.match(r'^\s+- name:', line):
        last_proxy_item_idx = len(result_pg)

    # 遇到下一个顶级 key（非 - name 开头的）则 in_group_proxies 结束
    if re.match(r'^[a-zA-Z]', line) and not line.startswith('-'):
        in_group_proxies = False

    result_pg.append(line)
    i += 1

# 处理最后一个组
if current_group_name and in_group_proxies and last_proxy_item_idx is not None:
    nodes_to_insert = group_inserts.get(current_group_name, [])
    if nodes_to_insert:
        insert_pos = last_proxy_item_idx + 1
        for nn in nodes_to_insert:
            nn_yaml = '  - ' + nn
            result_pg.insert(insert_pos, nn_yaml)
            insert_pos += 1
        print("  -> %s: 插入 %d 个节点" % (
            current_group_name.encode('utf-8') if isinstance(current_group_name,unicode) else current_group_name,
            len(nodes_to_insert)))

new_lines.extend(result_pg)

# 生成文件
mix_content = '\n'.join(new_lines) + '\n'
mix_bytes = mix_content.encode('utf-8')
local_mix = OUTDIR + '/mix.yaml'
open(local_mix, 'wb').write(mix_bytes)
print("\nmix.yaml 生成: %d bytes, %d 行" % (len(mix_bytes), len(new_lines)))

# 验证：检查 Proxies 组的节点数
proxies_count = 0
in_proxies_group = False
in_proxies_list = False
for line in new_lines:
    m = re.match(r'^- name:\s*(.+)', line)
    if m:
        raw = m.group(1).strip().strip('"\'')
        in_proxies_group = (raw == 'Proxies')
        in_proxies_list = False
    if in_proxies_group and re.match(r'^\s+proxies\s*:', line):
        in_proxies_list = True
    if in_proxies_group and in_proxies_list and re.match(r'^\s+- ', line):
        proxies_count += 1
print("验证: Proxies 组节点数 = %d" % proxies_count)

# 上传
print("\n上传到路由器...")
HCHUNK = 8192
nchunks = (len(mix_bytes) + HCHUNK - 1) // HCHUNK
for i in range(nchunks):
    chunk = mix_bytes[i*HCHUNK:(i+1)*HCHUNK]
    hex_str = binascii.hexlify(chunk)
    printf_str = ''.join(['\\x' + hex_str[j:j+2] for j in range(0, len(hex_str), 2)])
    redirect = '> /etc/openclash/config/mix.yaml' if i == 0 else '>> /etc/openclash/config/mix.yaml'
    ubus_exec('/bin/sh', ['-c', "printf '%s' %s" % (printf_str, redirect)], timeout=20)
    sys.stdout.write('.')
    sys.stdout.flush()
print(' done')

out, _ = ubus_exec('/bin/ls', ['-lh', '/etc/openclash/config/mix.yaml'])
print("路由器: %s" % out.strip())
