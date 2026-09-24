# -*- coding: utf-8 -*-
import re
from pathlib import Path
from collections import Counter, defaultdict

def parse_dbc(path):
    text = Path(path).read_text(encoding='utf-8', errors='ignore')
    msgs = []
    cur = None
    sig_re = re.compile(
        r'SG_\s+(\S+)\s*(?:\S+)?\s*:\s*(\d+)\|(\d+)@(\d+)([+-])\s*\(([^,]+),([^)]*)\)\s*\[([^|]*)\|([^]]*)\]\s*"(.*)"'
    )
    for line in text.splitlines():
        if line.startswith('BO_ '):
            m = re.match(r'BO_\s+(\d+)\s+([^:]+):\s*(\d+)\s+(\S+)', line)
            if m:
                cur = {
                    'id': int(m.group(1)),
                    'name': m.group(2).strip(),
                    'dlc': int(m.group(3)),
                    'node': m.group(4),
                    'signals': [],
                }
                msgs.append(cur)
        elif cur is not None and line.strip().startswith('SG_'):
            sm = sig_re.search(line)
            if sm:
                cur['signals'].append({
                    'name': sm.group(1),
                    'start': int(sm.group(2)),
                    'len': int(sm.group(3)),
                    'order': int(sm.group(4)),
                    'sign': sm.group(5),
                    'factor': sm.group(6).strip(),
                    'offset': sm.group(7).strip(),
                    'unit': sm.group(10),
                })
    return msgs

def asc_ids(path):
    pat = re.compile(r'^\s*[\d.]+\s+(?:\d+|---)\s+([0-9A-Fa-f]+)x?\s+(?:Rx|Tx)', re.I)
    ids = set()
    for line in Path(path).read_text(encoding='utf-8', errors='ignore').splitlines():
        if 'Status:' in line:
            continue
        m = pat.match(line)
        if m:
            ids.add(int(m.group(1), 16))
    return ids

ASC = r'D:\01.Lwq\01.Lwq\BMS测试\BMS测试-整合版\参考资料\test1.asc'
paths = [
    r'D:\01.Lwq\01.Lwq\BMS测试\BMS测试-整合版\参考资料\Ship_Two_5Cu12Pack_Matrix_Full_V1.91_20251207.dbc',
    r'D:\01.Lwq\01.Lwq\BMS测试\BMS测试-整合版\参考资料\对外通讯信号清单_二级架构5簇_CAN_V1.72(0818).dbc',
]
asc = asc_ids(ASC)
print('ASC unique', len(asc), 'sample', [hex(i) for i in sorted(asc)[:8]])

for p in paths:
    print('=' * 70)
    print(Path(p).name)
    msgs = parse_dbc(p)
    print(f'messages={len(msgs)} signals={sum(len(m["signals"]) for m in msgs)}')
    nodes = Counter(m['node'] for m in msgs)
    print('nodes:', nodes.most_common(8))
    # show first 20 with hex id
    for m in sorted(msgs, key=lambda x: x['id'])[:20]:
        print(f"  0x{m['id']:08X}  {m['name'][:48]:48s} dlc={m['dlc']} sigs={len(m['signals'])}")
    # compare with asc after stripping possible 29-bit layout
    dbc_ids = {m['id']: m for m in msgs}
    inter = asc & set(dbc_ids)
    print('direct intersect', len(inter))
    # try J1939-like: maybe dbc uses different ID encoding
    # show asc vs dbc hex side by side for similar names
    # Check if dbc ids when masked match asc
    # Common: dbc has 0x98...... vs bus 0x18......
    for mask_name, transform in [
        ('raw', lambda i: i),
        ('low29', lambda i: i & 0x1FFFFFFF),
        ('swap_like_18xx', lambda i: (i & 0x00FFFFFF) | 0x18000000),
        ('force_18', lambda i: 0x18000000 | (i & 0x00FFFFFF)),
    ]:
        mapped = {transform(i) for i in dbc_ids}
        print(f'  intersect via {mask_name}: {len(asc & mapped)}')

    # signal name groups
    prefixes = Counter()
    for m in msgs:
        prefixes[re.split(r'\d|_', m['name'])[0][:16] or m['name'][:8]] += 1
    print('name prefixes top:', prefixes.most_common(12))
    # sample signals of first msg
    if msgs:
        m0 = sorted(msgs, key=lambda x: x['id'])[0]
        print('sample signals of', m0['name'])
        for s in m0['signals'][:8]:
            print(f"   {s['name']}: start={s['start']} len={s['len']} order={s['order']} f={s['factor']} off={s['offset']} unit={s['unit']}")

# keyword frequency in signal names across both
print('=' * 70)
print('ASC vs 对外通讯 dbc id hex samples')
dbc2 = parse_dbc(paths[1])
print('dbc2 ids hex:', [f"0x{m['id']:08X}" for m in sorted(dbc2, key=lambda x:x['id'])[:15]])
print('asc ids hex:', [f"0x{i:08X}" for i in sorted(asc)[:15]])
