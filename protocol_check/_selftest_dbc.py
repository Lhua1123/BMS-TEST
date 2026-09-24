# -*- coding: utf-8 -*-
import os
import sys

ROOT = r"D:\01.Lwq\01.Lwq\BMS测试\BMS测试-整合版"
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from protocol_check.dbc_import import parse_dbc_file, dbc_id_to_bus_id
from protocol_check.excel_template import save_template_excel, load_template_excel
from protocol_check.log_parser import load_log_file
from protocol_check.checker import verify_frames

paths = [
    os.path.join(ROOT, "参考资料", "Ship_Two_5Cu12Pack_Matrix_Full_V1.91_20251207.dbc"),
    os.path.join(ROOT, "参考资料", "对外通讯信号清单_二级架构5簇_CAN_V1.72(0818).dbc"),
]
asc = os.path.join(ROOT, "参考资料", "test1.asc")
out = os.path.join(ROOT, "参考资料", "接收模板_从ShipTwo导出示例.xlsx")

print("map sample:", hex(0x98A3FFA1), "->", hex(dbc_id_to_bus_id(0x98A3FFA1)))

book, notes = parse_dbc_file(paths[0], map_id=True)
print("\n".join(notes))
print("messages", book.message_count, "signals", sum(len(m.signals) for m in book.messages.values()))

# 与实报交集
frames = load_log_file(asc)
frame_ids = {f.arbitration_id for f in frames}
mapped = set(book.messages.keys())
inter = frame_ids & mapped
print(f"ASC ids={len(frame_ids)} template={len(mapped)} intersect={len(inter)} only_asc={len(frame_ids-mapped)} only_dbc={len(mapped-frame_ids)}")

# 仅保留交集 + 必须出现，做一次核对
kept = 0
for mid in list(book.messages.keys()):
    if mid in inter:
        book.messages[mid].required = True
        kept += 1
    else:
        # 核对演示时先丢掉未出现的，避免海量 missing
        del book.messages[mid]
print("kept required messages", kept)
save_template_excel(book, out)
book2 = load_template_excel(out)
r = verify_frames(frames, book2)
print(r.summary_text)
cats = {}
for i in r.issues:
    cats[i.category] = cats.get(i.category, 0) + 1
print("issue cats", cats)

# 编译检查 tab
import tabs.protocol_check_tab as t
print("tab import ok", t.ProtocolCheckTab)
print("sample xlsx", out)
