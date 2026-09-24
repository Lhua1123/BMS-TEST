# -*- coding: utf-8 -*-
"""协议核对自测：生成模板 + 解析 test1.asc/blf + 跑核对引擎"""

import os
import sys
import traceback

ROOT = r"D:\01.Lwq\01.Lwq\BMS测试\BMS测试-整合版"
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from protocol_check.excel_template import build_sample_template, save_template_excel, load_template_excel
from protocol_check.log_parser import load_log_file
from protocol_check.checker import verify_frames

ASC = os.path.join(ROOT, "参考资料", "test1.asc")
BLF = os.path.join(ROOT, "参考资料", "test1.blf")
XLSX = os.path.join(ROOT, "参考资料", "接收CAN协议核对模板.xlsx")


def main():
    print("== 1. 生成示例 Excel 模板 ==")
    book = build_sample_template(asc_path=ASC)
    save_template_excel(book, XLSX)
    print(f"written: {XLSX}")
    book2 = load_template_excel(XLSX)
    print(f"reload messages={book2.message_count} signals={sum(len(m.signals) for m in book2.messages.values())}")

    print("\n== 2. 解析 ASC ==")
    frames = load_log_file(ASC)
    print(f"frames={len(frames)} unique={len({f.arbitration_id for f in frames})}")
    if frames:
        print("first:", hex(frames[0].arbitration_id), frames[0].data_hex)

    print("\n== 3. 核对 ASC ==")
    result = verify_frames(frames, book2)
    print(result.summary_text)
    cats = {}
    for i in result.issues:
        cats[i.category] = cats.get(i.category, 0) + 1
    print("issue categories:", cats)
    for i in result.issues[:12]:
        print(f"  [{i.level}] {i.category} 0x{i.msg_id_hex}: {i.message}")

    print("\n== 4. 解析 BLF ==")
    try:
        blf_frames = load_log_file(BLF)
        print(f"blf_frames={len(blf_frames)} unique={len({f.arbitration_id for f in blf_frames})}")
        if blf_frames:
            r2 = verify_frames(blf_frames, book2)
            print("BLF", r2.summary_text)
    except Exception as e:
        print("BLF failed:", e)
        traceback.print_exc()

    print("\nOK")


if __name__ == "__main__":
    main()
