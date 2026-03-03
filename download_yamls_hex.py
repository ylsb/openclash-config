# -*- coding: utf-8 -*-
"""
下载路由器1上的5个yaml文件，合并节点到mix.yaml，上传回路由器
"""
import json, urllib2, os, sys, binascii
reload(sys); sys.setdefaultencoding('utf-8')

BASE = 'http://192.168.3.1'

def get_session():
    req = urllib2.Request(BASE + '/ubus/')
    req.add_header('Content-Type', 'application/json')
    req.add_data(json.dumps({"jsonrpc":"2.0","id":1,"method":"call","params":["00000000000000000000000000000000","session","login",{"username":"root","password":"root"}]}))
    return json.loads(urllib2.urlopen(req, timeout=8).read())['result'][1]['ubus_rpc_session']

SESSION = get_session()

def ubus_exec(cmd, args, timeout=60):
    req = urllib2.Request(BASE + '/ubus/')
    req.add_header('Content-Type', 'application/json')
    req.add_data(json.dumps({"jsonrpc":"2.0","id":1,"method":"call","params":[SESSION,"file","exec",{"command":cmd,"params":args}]}))
    r = json.loads(urllib2.urlopen(req, timeout=timeout+5).read()).get('result',[])
    if len(r) > 1 and isinstance(r[1], dict):
        return r[1].get('stdout',''), r[1].get('stderr',''), r[1].get('code',-1)
    return '', '', -1

def ubus_write(path, data):
    req = urllib2.Request(BASE + '/ubus/')
    req.add_header('Content-Type', 'application/json')
    if isinstance(data, unicode):
        data = data.encode('utf-8')
    req.add_data(json.dumps({"jsonrpc":"2.0","id":1,"method":"call","params":[SESSION,"file","write",{"path":path,"data":data}]}))
    r = json.loads(urllib2.urlopen(req, timeout=30).read()).get('result',[])
    return r[0] == 0 if r else False

def download_via_hex(remote_path):
    """用 hexdump 分块读取大文件"""
    # 先获取文件大小
    out, _, _ = ubus_exec('/bin/sh', ['-c', 'wc -c < %s' % remote_path])
    total = int(out.strip()) if out.strip().isdigit() else 0
    print("  文件大小: %d bytes" % total)

    CHUNK = 32768  # 32KB per chunk
    all_hex = ''
    offset = 0
    chunk_num = 0
    while offset < total or (total == 0 and chunk_num == 0):
        out, err, code = ubus_exec('/bin/sh', ['-c',
            'hexdump -v -e \'"" 1/1 "%%02x"\' -s %d -n %d %s 2>/dev/null' % (offset, CHUNK, remote_path)],
            timeout=30)
        if not out:
            break
        all_hex += out.strip()
        offset += CHUNK
        chunk_num += 1
        sys.stdout.write('.')
        sys.stdout.flush()
        if len(out.strip()) < CHUNK * 2:  # last chunk
            break
    print(" done (%d hex chars)" % len(all_hex))
    if all_hex:
        return binascii.unhexlify(all_hex)
    return None

OUTDIR = '/tmp/yaml_merge'
if not os.path.exists(OUTDIR):
    os.makedirs(OUTDIR)

files = ['Nexitally_1.yaml', 'Nexitally_2.yaml', 'Nexitally_3.yaml', 'kendeji.yaml', 'test.yaml']

for fname in files:
    print("下载 %s ..." % fname)
    data = download_via_hex('/etc/openclash/' + fname)
    if data:
        open(OUTDIR + '/' + fname, 'wb').write(data)
        print("  保存完成: %d bytes" % len(data))
    else:
        print("  失败!")

print("\n已下载:")
for f in os.listdir(OUTDIR):
    print("  %s: %d bytes" % (f, os.path.getsize(OUTDIR + '/' + f)))
