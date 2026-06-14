# -*- coding: utf-8 -*-
"""
复现：转运批次取消后，桶清单被清空的问题
修复前后都可以跑，输出对比明显
"""
import requests
import json
import sys

BASE = "http://localhost:5000/api/v1"


def POST(path, data, expect=200):
    r = requests.post(BASE + path, json=data, timeout=5)
    print(f"  POST {path} -> {r.status_code}")
    if r.status_code != expect:
        print(f"    响应: {r.text[:300]}")
    return r.status_code, r.json() if r.text else {}


def GET(path):
    r = requests.get(BASE + path, timeout=5)
    print(f"  GET {path} -> {r.status_code}")
    return r.status_code, r.json() if r.text else {}


def create_and_prepare_barrel(no, weight, loc_id=2):
    """创建->称重->复核，返回桶ID和桶号"""
    code, data = POST("/barrels", {
        "barrel_no": no,
        "waste_category_id": 2,
        "operator_role": "WORKSHOP",
        "operator_name": "张工"
    }, 201)
    barrel_id = (data or {}).get("id")
    if not barrel_id:
        print(f"  建桶失败: {no}")
        return None, None
    barrel_no = (data or {}).get("barrel_no", no)
    POST(f"/barrels/{barrel_id}/weigh", {
        "weight_kg": weight,
        "storage_location_id": loc_id,
        "tag_code": f"TAG-{no}",
        "operator_role": "WAREHOUSE",
        "operator_name": "李仓管"
    })
    POST(f"/barrels/{barrel_id}/review", {
        "operator_role": "ENV_AUDITOR",
        "operator_name": "王复核",
        "notes": "ok"
    })
    return barrel_id, barrel_no


def check(name, cond, detail=""):
    mark = "✅" if cond else "❌"
    print(f"  {mark} 检查[{name}]: {'通过' if cond else '失败'} {detail}")
    return cond


def main():
    print("=" * 60)
    print("【问题复现】转运批次取消后桶清单追溯验证")
    print("=" * 60)

    # 1. 准备两个桶
    print("\n[1] 准备两个已复核桶")
    bid_a, bno_a = create_and_prepare_barrel(f"RPT-A-{sys.argv[1] if len(sys.argv)>1 else '001'}", 150.0)
    bid_b, bno_b = create_and_prepare_barrel(f"RPT-B-{sys.argv[1] if len(sys.argv)>1 else '001'}", 200.5)
    if not bid_a or not bid_b:
        print("准备桶失败，终止")
        return

    # 2. 创建批次
    print(f"\n[2] 创建批次，桶ID=[{bid_a}, {bid_b}]")
    batch_no = f"BATCH-RPT-{sys.argv[1] if len(sys.argv)>1 else '001'}"
    code, batch_data = POST("/batches", {
        "batch_no": batch_no,
        "vehicle_no": "京A-RPT01",
        "driver_name": "钱司机",
        "driver_phone": "13900000001",
        "expected_exit_time": "2026-06-30T10:00:00",
        "manifest_no": "HB-RPT-001",
        "barrel_ids": [bid_a, bid_b],
        "operator_role": "TRANSPORT",
        "operator_name": "钱司机"
    }, 201)
    batch_id = (batch_data or {}).get("id")
    if not batch_id:
        print("创建批次失败，终止")
        return

    # 3. 取消前快照（详情 + JSON导出）
    print(f"\n[3] 取消前 - 查询批次详情和导出")
    _, detail_before = GET(f"/batches/{batch_id}")
    _, json_export_before_raw = GET("/batches/export/json")
    json_export_before = json_export_before_raw.get("batches", [])
    barrel_count_before = detail_before.get("barrel_count", -1)
    barrel_ids_before = sorted([b["id"] for b in detail_before.get("barrels", [])])
    batch_in_export_before = next(
        (b for b in json_export_before if b["id"] == batch_id), None
    )
    export_count_before = batch_in_export_before.get("barrel_count", -1) if batch_in_export_before else -1
    export_barrel_ids_before = sorted(
        [b["barrel_id"] for b in batch_in_export_before.get("barrels", [])]
    ) if batch_in_export_before else []

    check("取消前-详情桶数量", barrel_count_before == 2, f"{barrel_count_before}")
    check("取消前-详情桶ID正确", barrel_ids_before == sorted([bid_a, bid_b]), f"{barrel_ids_before}")
    check("取消前-JSON导出桶数量", export_count_before == 2, f"{export_count_before}")
    check("取消前-JSON导出桶ID正确", export_barrel_ids_before == sorted([bid_a, bid_b]), f"{export_barrel_ids_before}")

    # 4. 取消批次
    print(f"\n[4] 取消批次 id={batch_id}")
    cancel_reason = "复现测试：取消后追溯问题"
    POST(f"/batches/{batch_id}/cancel", {
        "cancel_reason": cancel_reason,
        "operator_role": "ENV_AUDITOR",
        "operator_name": "王复核"
    })

    # 5. 取消后快照（详情 + JSON导出）
    print(f"\n[5] 取消后 - 查询批次详情和导出 (★关键检查点★)")
    _, detail_after = GET(f"/batches/{batch_id}")
    _, json_export_after_raw = GET("/batches/export/json")
    json_export_after = json_export_after_raw.get("batches", [])

    barrel_count_after = detail_after.get("barrel_count", -1)
    barrels_after = detail_after.get("barrels", [])
    barrel_ids_after = sorted([b.get("id") for b in barrels_after])
    barrel_nos_after = sorted([b.get("barrel_no", "?") for b in barrels_after])
    batch_status_after = detail_after.get("status", "?")
    cancel_reason_after = detail_after.get("cancel_reason", "")

    batch_in_export_after = next(
        (b for b in json_export_after if b["id"] == batch_id), None
    )
    export_count_after = batch_in_export_after.get("barrel_count", -1) if batch_in_export_after else -1
    export_barrel_ids_after = sorted(
        [b.get("barrel_id") for b in batch_in_export_after.get("barrels", [])]
    ) if batch_in_export_after else []
    export_status_after = batch_in_export_after.get("status", "?") if batch_in_export_after else "?"
    export_cancel_reason_after = batch_in_export_after.get("cancel_reason", "") if batch_in_export_after else ""

    print(f"  --- 详情字段 ---")
    print(f"    batch_status    = {batch_status_after}")
    print(f"    cancel_reason   = {cancel_reason_after}")
    print(f"    barrel_count    = {barrel_count_after}")
    print(f"    barrel_ids      = {barrel_ids_after}")
    print(f"    barrel_nos      = {barrel_nos_after}")
    print(f"  --- JSON导出字段 ---")
    print(f"    export_status   = {export_status_after}")
    print(f"    export_cancel   = {export_cancel_reason_after}")
    print(f"    export_count    = {export_count_after}")
    print(f"    export_barrel_ids= {export_barrel_ids_after}")

    results = []
    # ★ 核心问题点：取消后桶数量和桶ID是否还能看到
    results.append(check("★取消后-详情桶数量(应为2)", barrel_count_after == 2,
                         f"实际={barrel_count_after} {'← 问题复现！' if barrel_count_after != 2 else ''}"))
    results.append(check("★取消后-详情桶ID正确", barrel_ids_after == sorted([bid_a, bid_b]),
                         f"实际={barrel_ids_after}"))
    results.append(check("★取消后-详情桶号正确", barrel_nos_after == sorted([bno_a, bno_b]),
                         f"实际={barrel_nos_after}"))
    results.append(check("取消后-批次状态=CANCELLED", batch_status_after == "CANCELLED",
                         f"实际={batch_status_after}"))
    results.append(check("取消后-取消原因保留", cancel_reason_after == cancel_reason,
                         f"实际='{cancel_reason_after}'"))
    results.append(check("★取消后-JSON导出桶数量(应为2)", export_count_after == 2,
                         f"实际={export_count_after} {'← 问题复现！' if export_count_after != 2 else ''}"))
    results.append(check("★取消后-JSON导出桶ID正确", export_barrel_ids_after == sorted([bid_a, bid_b]),
                         f"实际={export_barrel_ids_after}"))
    results.append(check("取消后-JSON导出状态=CANCELLED", export_status_after == "CANCELLED",
                         f"实际={export_status_after}"))
    results.append(check("取消后-JSON导出取消原因保留", export_cancel_reason_after == cancel_reason,
                         f"实际='{export_cancel_reason_after}'"))

    # 6. 验证桶状态恢复正确（不能被修复带坏）
    print(f"\n[6] 验证桶状态恢复为 REVIEWED（不能被修复带坏）")
    _, ba = GET(f"/barrels/{bid_a}")
    _, bb = GET(f"/barrels/{bid_b}")
    results.append(check(f"桶A状态=REVIEWED", ba.get("status") == "REVIEWED", f"实际={ba.get('status')}"))
    results.append(check(f"桶B状态=REVIEWED", bb.get("status") == "REVIEWED", f"实际={bb.get('status')}"))
    results.append(check(f"桶A batch_id=None", ba.get("transport_batch_id") is None,
                         f"实际={ba.get('transport_batch_id')}"))
    results.append(check(f"桶B batch_id=None", bb.get("transport_batch_id") is None,
                         f"实际={bb.get('transport_batch_id')}"))

    # 7. 验证取消后可以重新合批（不能被修复带坏）
    print(f"\n[7] 验证取消后可以重新合批（不能被修复带坏）")
    re_batch_no = f"BATCH-RPT-RE-{sys.argv[1] if len(sys.argv)>1 else '001'}"
    code2, re_batch_data = POST("/batches", {
        "batch_no": re_batch_no,
        "vehicle_no": "京A-RPT02",
        "driver_name": "钱司机",
        "expected_exit_time": "2026-06-30T12:00:00",
        "manifest_no": "HB-RPT-RE-001",
        "barrel_ids": [bid_a, bid_b],
        "operator_role": "TRANSPORT",
        "operator_name": "钱司机"
    }, 201)
    results.append(check("取消后可重新合批成功", code2 == 201,
                         f"实际状态码={code2}"))

    # 汇总
    print("\n" + "=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"汇总: {passed}/{total} 通过")
    print("=" * 60)
    if passed == total:
        print("✅ 所有检查通过，问题已修复或未出现")
    else:
        print("❌ 有检查未通过，如果是 ★标记项=问题已成功复现")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
