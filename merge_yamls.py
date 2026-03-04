# -*- coding: utf-8 -*-
"""
merge_yamls.py - 最终版 (v6)

合并多个 OpenClash YAML 订阅配置，生成 mix.yaml 并上传到路由器。

用法:
    python2 merge_yamls.py

配置:
    - ROUTER_IP: 路由器 IP
    - ROUTER_API_TOKEN: Clash API token
    - YAML_DIR: 本地 YAML 文件目录
    - BASE_YAML: 基础配置文件（用其 header + proxy-groups + rules）
    - EXTRA_YAMLS: 额外订阅文件（只取其 proxies 块追加）
    - OUTPUT: 输出文件名

逻辑:
    1. 从 BASE_YAML 提取 138 个基础节点
    2. 从 EXTRA_YAMLS 依次追加去重节点（按 name + server:port 去重）
    3. 过滤流量/套餐/到期等信息节点
    4. 重建所有策略组的 proxies 列表：
       - 普通组（Netflix/AI/Google/Telegram 等）→ 全量节点
       - Final 组 → 全量节点（可手动选任意节点）
       - Direct 组 → [DIRECT, Proxies]（固定）
    5. 所有策略组节点引用加双引号（避免 YAML Unicode 转义解析歧义）
    6. 上传到路由器 /etc/openclash/config/mix.yaml

注意:
    - 依赖 Python 2.7（Synology NAS 环境）
    - 通过 ubus HTTP API 操作路由器（不需要 SSH）
    - 使用 printf hex 分块上传大文件（OpenWrt 无 base64）
"""
import re, sys, binascii, json, urllib2

# ==================== 配置 ====================
ROUTER_IP = "192.168.3.1"
API_TOKEN = "NbAc1bNm"
YAML_DIR  = "/tmp/yaml_merge2"
BASE_YAML = "Nexitally_1.yaml"
EXTRA_YAMLS = ["kendeji.yaml", "test.yaml"]
OUTPUT_NAME = "mix.yaml"
UPLOAD_PATH = "/etc/openclash/config/mix.yaml"
# ==============================================

BASE = "http://" + ROUTER_IP

def get_session():
    req = urllib2.Request(BASE + "/ubus/")
    req.add_header("Content-Type", "application/json")
    req.add_data(json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "call",
        "params": ["00000000000000000000000000000000", "session", "login",
                   {"username": "root", "password": "root"}]
    }))
    return json.loads(urllib2.urlopen(req, timeout=8).read())["result"][1]["ubus_rpc_session"]

SESSION = get_session()

def ubus_exec(cmd, args, timeout=30):
    req = urllib2.Request(BASE + "/ubus/")
    req.add_header("Content-Type", "application/json")
    req.add_data(json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "call",
        "params": [SESSION, "file", "exec", {"command": cmd, "params": args}]
    }))
    r = json.loads(urllib2.urlopen(req, timeout=timeout+5).read()).get("result", [])
    if len(r) > 1 and isinstance(r[1], dict):
        return r[1].get("stdout", "")
    return ""

def extract_blocks(raw):
    """从 proxies 块提取所有代理条目（bytes 操作，保留原始格式）"""
    blocks = []; cur = []; in_p = False
    for line in raw.split(b"\n"):
        if re.match(b"^proxies\\s*:", line):
            in_p = True; continue
        if in_p and re.match(b"^[a-zA-Z]", line) and not line.startswith(b"-"):
            if cur: blocks.append(b"\n".join(cur)); cur = []
            in_p = False; continue
        if not in_p: continue
        s = line.strip()
        is_new = re.match(b"^-\\s+(name:|\\{)", s)
        if is_new:
            if cur: blocks.append(b"\n".join(cur))
            cur = [s]
        elif cur:
            first = cur[0].strip()
            if re.match(b"^-\\s+\\{", first) and first.rstrip().endswith(b"}"):
                blocks.append(b"\n".join(cur)); cur = []
                if is_new: cur = [s]
            else:
                cur.append(line)
    if cur: blocks.append(b"\n".join(cur))
    return blocks

def get_name(block):
    """提取节点名（bytes，保留原始 unicode 转义格式）"""
    sq = b"'"
    dq = b'"'
    m = re.search(b"name:\\s*" + sq + b"([^" + sq + b"]+)" + sq, block)
    if m: return m.group(1)
    m = re.search(b"name:\\s*" + dq + b"([^" + dq + b"]+)" + dq, block)
    if m: return m.group(1)
    m = re.search(b"^-\\s+name:\\s*(.+)", block, re.MULTILINE)
    if m: return m.group(1).strip().strip(b"\"'")
    m = re.search(b"name:\\s*([^,}\n]+)", block)
    if m: return m.group(1).strip().strip(b"\"'")
    return None

def get_server_port(block):
    s = re.search(b"server:\\s*(\\S+)", block)
    p = re.search(b"\\bport:\\s*(\\S+)", block)
    return (s.group(1) if s else b"", p.group(1).rstrip(b",}") if p else b"")

def normalize(block):
    """单行 {name:...} 格式去掉前缀空格"""
    out = []
    for l in block.split(b"\n"):
        s = l.strip()
        out.append(s if (s.startswith(b"- {") or s.startswith(b"-{")) else l)
    return b"\n".join(out)

# 信息节点关键词（过滤套餐/流量/到期等）
INFO_KEYWORDS = [b" G |", b" GB", b"Traffic", b"Expire", b"Reset", b"Days Left"]
def is_info_node(n):
    return not n or any(k in n for k in INFO_KEYWORDS)

def build_proxies(base_raw, extra_raws):
    """合并所有节点，返回 (blocks_list, names_list)"""
    seen_names = set(); seen_sp = set(); blocks = []
    for b in extract_blocks(base_raw):
        n = get_name(b); sp = get_server_port(b)
        if is_info_node(n): continue
        if n and n in seen_names: continue
        if sp[0] and sp in seen_sp: continue
        if n: seen_names.add(n)
        if sp[0]: seen_sp.add(sp)
        blocks.append(normalize(b))
    print "Base (%s): %d nodes" % (BASE_YAML, len(blocks))

    for raw, fname in extra_raws:
        added = 0
        for b in extract_blocks(raw):
            n = get_name(b); sp = get_server_port(b)
            if is_info_node(n): continue
            if n and n in seen_names: continue
            if sp[0] and sp in seen_sp: continue
            if n: seen_names.add(n)
            if sp[0]: seen_sp.add(sp)
            blocks.append(normalize(b))
            added += 1
        print "%s: +%d" % (fname, added)

    names = [get_name(b) for b in blocks if get_name(b)]
    print "Total: %d nodes" % len(names)
    return blocks, names

def rebuild_proxy_groups(pg_raw_lines, all_names):
    """重建策略组 proxies 列表"""
    result = []
    cur_grp = None; replacing = False
    i = 0
    while i < len(pg_raw_lines):
        line = pg_raw_lines[i]
        m = re.match(b"^- name:\\s*(.+)", line)
        if m:
            cur_grp = m.group(1).strip().strip(b"\"'")
            replacing = False
            result.append(line); i += 1; continue
        if re.match(b"^\\s+proxies\\s*:", line) and cur_grp is not None:
            result.append(line)
            if cur_grp.endswith(b"Direct"):
                result.append(b"  - DIRECT")
                result.append(b"  - Proxies")
            else:
                # 所有节点引用加双引号（避免 YAML Unicode 转义歧义）
                for nn in all_names:
                    result.append(b'  - "' + nn + b'"')
            replacing = True
            i += 1; continue
        if replacing and re.match(b"^\\s+- ", line):
            i += 1; continue
        elif replacing:
            replacing = False
        result.append(line); i += 1
    return result

def validate(mix, all_names):
    """验证各策略组节点数"""
    def cnt(grp_bytes):
        lines = mix.split(b"\n"); in_g = in_p = False; c = 0
        for l in lines:
            mm = re.match(b"^- name:\\s*(.+)", l)
            if mm: rn = mm.group(1).strip().strip(b"\"'"); in_g = (rn == grp_bytes); in_p = False
            if in_g and re.match(b"^\\s+proxies\\s*:", l): in_p = True
            if in_g and in_p and re.match(b"^\\s+- ", l): c += 1
        return c
    for g in [b"Proxies", b"Netflix", b"Google", b"AI", b"Telegram"]:
        print "  %s: %d" % (g, cnt(g))
    # Direct
    ls = mix.split(b"\n"); in_g = in_p = False; c = 0
    for l in ls:
        mm = re.match(b"^- name:\\s*(.+)", l)
        if mm: rn = mm.group(1).strip().strip(b"\"'"); in_g = rn.endswith(b"Direct"); in_p = False
        if in_g and re.match(b"^\\s+proxies\\s*:", l): in_p = True
        if in_g and in_p and re.match(b"^\\s+- ", l): c += 1
    print "  Direct: %d" % c

def upload(mix_bytes, dest_path):
    HCHUNK = 8192
    n = (len(mix_bytes) + HCHUNK - 1) // HCHUNK
    for idx in range(n):
        chunk = mix_bytes[idx*HCHUNK:(idx+1)*HCHUNK]
        hs = binascii.hexlify(chunk)
        ps = "".join(["\\x" + hs[j:j+2] for j in range(0, len(hs), 2)])
        rd = "> " + dest_path if idx == 0 else ">> " + dest_path
        ubus_exec("/bin/sh", ["-c", "printf '%s' %s" % (ps, rd)], timeout=20)
        sys.stdout.write("."); sys.stdout.flush()
    print " done"
    return ubus_exec("/bin/ls", ["-lh", dest_path])

# ==================== Main ====================
base_raw = open(YAML_DIR + "/" + BASE_YAML, "rb").read()
extra_raws = [(open(YAML_DIR + "/" + f, "rb").read(), f) for f in EXTRA_YAMLS
              if __import__("os").path.exists(YAML_DIR + "/" + f)]

proxy_blocks, all_names = build_proxies(base_raw, extra_raws)

base_lines = base_raw.split(b"\n")
proxy_start = next(i for i, l in enumerate(base_lines) if re.match(b"^proxies\\s*:", l))
proxy_end = next(i for i in range(proxy_start+1, len(base_lines))
                  if re.match(b"^[a-zA-Z]", base_lines[i]) and not base_lines[i].startswith(b"-"))

header = b"\n".join(base_lines[:proxy_start])
pg_raw_lines = base_lines[proxy_end:]
new_proxy_block = b"proxies:\n" + b"\n".join(proxy_blocks)
new_pg = rebuild_proxy_groups(pg_raw_lines, all_names)

mix = header + b"\n" + new_proxy_block + b"\n\n" + b"\n".join(new_pg) + b"\n"
mix_bytes = mix  # already bytes

print "\nValidating:"
validate(mix, all_names)

out_path = YAML_DIR + "/" + OUTPUT_NAME
open(out_path, "wb").write(mix_bytes)
print "\nSaved: %s (%d bytes)" % (out_path, len(mix_bytes))

print "\nUploading to %s..." % UPLOAD_PATH
print upload(mix_bytes, UPLOAD_PATH)
