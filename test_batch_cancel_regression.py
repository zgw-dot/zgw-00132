# -*- coding: utf-8 -*-
"""
转运批次取消追溯 - 完整回归测试（两阶段执行）

执行方式：
  1) python test_batch_cancel_regression.py REG1 --step1
     * 创建两桶 → 合批 → 取消 → 验证取消后状态 → 写入快照
     * 输出提示让用户手动重启服务

  2) （用户手动重启服务后）
     python test_batch_cancel_regression.py REG1 --step2
     * 读取快照 → 重新查询验证 → 对比重启前后一致性

覆盖检查点：
  - 取消后：详情桶数/桶ID/桶号正确、状态/取消原因保留
  - 取消后：列表 API barrel_count、JSON/CSV 导出完整
  - 取消后：桶恢复为 REVIEWED、batch_id 清空（不带坏现有逻辑）
  - 重启后：所有字段与重启前完全一致
  - 核对字段直接面向用户可见输出，不做内部遍历
"""
import requests
import json
import sys
import os

BASE = "http://localhost:5000/api/v1"
SNAPSHOT_DIR = "regression_snapshots"


def POST(path, data, expect=200):
    r = requests.post(BASE + path, json=data, timeout=5)
    if r.status_code != expect:
        print(f"  POST {path} -> {r.status_code} | {r.text[:250]}")
    return r.status_code, (r.json() if r.text else {})


def GET(path):
    r = requests.get(BASE + path, timeout=5)
    return r.status_code, (r.json() if r.text else {})


def GET_CSV(path):
    r = requests.get(BASE + path, timeout=5)
    return r.status_code, r.text


def create_barrel_full(no, weight, loc_id=2):
    POST("/barrels", {
        "barrel_no": no,
        "waste_category_id": 2,
        "operator_role": "WORKSHOP",
        "operator_name": "张工"
    }, 201)
    barrel_id = None
    _, all_b = GET("/barrels")
    for b in all_b:
        if b["barrel_no"] == no:
            barrel_id = b["id"]
            break
    if not barrel_id:
        raise RuntimeError(f"桶 {no} 创建后查不到ID")
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
    return barrel_id, no


def check(name, cond, detail=""):
    mark = "✅" if cond else "❌"
    print(f"  {mark} {name}: {'通过' if cond else '失败'} {detail}")
    return cond


def snapshot_path(tag):
    if not os.path.exists(SNAPSHOT_DIR):
        os.makedirs(SNAPSHOT_DIR)
    return os.path.join(SNAPSHOT_DIR, f"snapshot_{tag}.json")


def build_snapshot(batch_id, bid_a, bid_b, bno_a, bno_b, batch_no, cancel_reason):
    """采集所有用户可见字段的快照"""
    _, detail = GET(f"/batches/{batch_id}")
    _, batch_list = GET("/batches")
    _, json_exp_raw = GET("/batches/export/json")
    _, csv_text = GET_CSV("/batches/export/csv")
    _, ba = GET(f"/barrels/{bid_a}")
    _, bb = GET(f"/barrels/{bid_b}")

    batch_in_list = next((b for b in batch_list if b["id"] == batch_id), None)
    batch_in_json = next(
        (b for b in json_exp_raw.get("batches", []) if b["id"] == batch_id), None
    )

    return {
        "meta": {
            "batch_id": batch_id,
            "bid_a": bid_a, "bid_b": bid_b,
            "bno_a": bno_a, "bno_b": bno_b,
            "batch_no": batch_no,
            "cancel_reason": cancel_reason,
        },
        "detail": detail,
        "list_barrel_count": batch_in_list.get("barrel_count") if batch_in_list else None,
        "json_export": batch_in_json,
        "csv_text": csv_text,
        "barrel_a": ba,
        "barrel_b": bb,
    }


def verify_snapshot(snap, label):
    """用户可见字段核对"""
    m = snap["meta"]
    exp_ids = sorted([m["bid_a"], m["bid_b"]])
    exp_nos = sorted([m["bno_a"], m["bno_b"]])
    total_weight = 350.5  # 150.0 + 200.5
    results = []

    d = snap["detail"]
    detail_ids = sorted([b["id"] for b in d.get("barrels", [])])
    detail_nos = sorted([b["barrel_no"] for b in d.get("barrels", [])])
    results.append(check(f"{label} 详情桶数量=2", d.get("barrel_count") == 2, f"实际={d.get('barrel_count')}"))
    results.append(check(f"{label} 详情桶ID匹配", detail_ids == exp_ids, f"{detail_ids}"))
    results.append(check(f"{label} 详情桶号匹配", detail_nos == exp_nos, f"{detail_nos}"))
    results.append(check(f"{label} 详情状态=CANCELLED", d.get("status") == "CANCELLED", f"实际={d.get('status')}"))
    results.append(check(f"{label} 详情取消原因", d.get("cancel_reason") == m["cancel_reason"], f"'{d.get('cancel_reason')}'"))
    results.append(check(f"{label} 详情取消角色=ENV_AUDITOR", d.get("cancelled_by_role") == "ENV_AUDITOR", f"{d.get('cancelled_by_role')}"))
    results.append(check(f"{label} 详情取消人=王复核", d.get("cancelled_by_name") == "王复核", f"'{d.get('cancelled_by_name')}'"))
    results.append(check(f"{label} 详情取消时间非空", d.get("cancelled_at") not in (None, ""), f"{d.get('cancelled_at')}"))
    results.append(check(f"{label} 详情批次号", d.get("batch_no") == m["batch_no"], f"'{d.get('batch_no')}'"))
    results.append(check(f"{label} 详情总重量=350.5", d.get("total_weight_kg") == total_weight, f"{d.get('total_weight_kg')}"))

    results.append(check(f"{label} 列表API桶数量=2", snap["list_barrel_count"] == 2, f"实际={snap['list_barrel_count']}"))

    je = snap["json_export"]
    if je:
        j_ids = sorted([b.get("barrel_id") for b in je.get("barrels", [])])
        results.append(check(f"{label} JSON导出桶数量=2", je.get("barrel_count") == 2, f"{je.get('barrel_count')}"))
        results.append(check(f"{label} JSON导出桶ID匹配", j_ids == exp_ids, f"{j_ids}"))
        results.append(check(f"{label} JSON导出状态=CANCELLED", je.get("status") == "CANCELLED", f"{je.get('status')}"))
        results.append(check(f"{label} JSON导出取消原因", je.get("cancel_reason") == m["cancel_reason"], f"'{je.get('cancel_reason')}'"))
        results.append(check(f"{label} JSON导出总重量", je.get("total_weight_kg") == total_weight, f"{je.get('total_weight_kg')}"))
        results.append(check(f"{label} JSON导出联单号", je.get("manifest_no") == f"HB-REG-{m['tag_ref'] if 'tag_ref' in m else sys.argv[1]}",
                             f"'{je.get('manifest_no')}'"))
    else:
        results.append(check(f"{label} JSON导出批次存在", False, "未找到目标批次"))

    # CSV 检查：逐行搜索，直接对用户看到的文本
    csv_text = snap["csv_text"]
    lines = csv_text.strip().split("\n")
    header_cols = lines[0].split(",") if lines else []
    target_line = None
    for line in lines[1:]:
        if m["batch_no"] in line.split(",")[0]:  # 第一列是批次号
            target_line = line
            break
    if target_line:
        cols = target_line.split(",")
        results.append(check(f"{label} CSV存在目标批次行", True))
        results.append(check(f"{label} CSV第1列=批次号", cols[0].strip() == m["batch_no"], f"'{cols[0].strip()}'"))
        results.append(check(f"{label} CSV桶数量列=2", "2" in cols[7].strip() if len(cols) > 7 else False, f"cols[7]={cols[7] if len(cols) > 7 else 'N/A'}"))
        results.append(check(f"{label} CSV状态列=CANCELLED",
                             "CANCELLED" in (cols[9].strip() if len(cols) > 9 else ""),
                             f"cols[9]={cols[9] if len(cols) > 9 else 'N/A'}"))
        results.append(check(f"{label} CSV包含桶A号", m["bno_a"] in target_line,
                             f"桶A出现={m['bno_a'] in target_line}"))
        results.append(check(f"{label} CSV包含桶B号", m["bno_b"] in target_line,
                             f"桶B出现={m['bno_b'] in target_line}"))
        results.append(check(f"{label} CSV取消原因存在",
                             len(cols) > 10 and len(cols[10].strip()) > 0,
                             f"cols[10]='{cols[10] if len(cols) > 10 else 'N/A'}'"))
    else:
        results.append(check(f"{label} CSV中找到目标批次行", False, f"搜索批次号={m['batch_no']}"))

    results.append(check(f"{label} 桶A状态=REVIEWED", snap["barrel_a"].get("status") == "REVIEWED",
                         f"实际={snap['barrel_a'].get('status')}"))
    results.append(check(f"{label} 桶B状态=REVIEWED", snap["barrel_b"].get("status") == "REVIEWED",
                         f"实际={snap['barrel_b'].get('status')}"))
    results.append(check(f"{label} 桶A batch_id=None", snap["barrel_a"].get("transport_batch_id") is None,
                         f"实际={snap['barrel_a'].get('transport_batch_id')}"))
    results.append(check(f"{label} 桶B batch_id=None", snap["barrel_b"].get("transport_batch_id") is None,
                         f"实际={snap['barrel_b'].get('transport_batch_id')}"))
    return results


def run_step1(tag):
    print("=" * 65)
    print(f"[Step 1/2] 建数据 + 取消 + 验证 + 存快照")
    print("=" * 65)

    bid_a, bno_a = create_barrel_full(f"REG-A-{tag}", 150.0)
    bid_b, bno_b = create_barrel_full(f"REG-B-{tag}", 200.5)
    cancel_reason = f"回归测试-取消原因-{tag}"
    batch_no = f"BATCH-REG-{tag}"
    print(f"\n  桶A id={bid_a} ({bno_a}), 桶B id={bid_b} ({bno_b})")
    print(f"  批次号={batch_no}, 取消原因={cancel_reason}")

    _, batch = POST("/batches", {
        "batch_no": batch_no,
        "vehicle_no": f"京A-REG{tag}",
        "driver_name": "钱司机",
        "expected_exit_time": "2026-06-30T10:00:00",
        "manifest_no": f"HB-REG-{tag}",
        "barrel_ids": [bid_a, bid_b],
        "operator_role": "TRANSPORT",
        "operator_name": "钱司机"
    }, 201)
    batch_id = batch["id"]
    print(f"  批次已创建 id={batch_id}")

    POST(f"/batches/{batch_id}/cancel", {
        "cancel_reason": cancel_reason,
        "operator_role": "ENV_AUDITOR",
        "operator_name": "王复核"
    })
    print(f"  批次已取消")

    # 验证取消后
    print(f"\n[取消后验证]")
    snap = build_snapshot(batch_id, bid_a, bid_b, bno_a, bno_b, batch_no, cancel_reason)
    snap["meta"]["tag_ref"] = tag
    r1 = verify_snapshot(snap, "取消后")

    # 存快照
    sp = snapshot_path(tag)
    with open(sp, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n  快照已保存: {sp}")

    # 提示手动重启
    print("\n" + "=" * 65)
    print(f"[Step 1 完成] 取消后验证 {sum(r1)}/{len(r1)} 通过")
    print("=" * 65)
    print("")
    print("下一步操作：")
    print("  1. 停止当前 Flask 服务（终端按 Ctrl+C）")
    print("  2. 重新启动: python run.py")
    print(f"  3. 再次执行: python {sys.argv[0]} {tag} --step2")
    print("")
    return 0 if sum(r1) == len(r1) else 1


def run_step2(tag):
    print("=" * 65)
    print(f"[Step 2/2] 重启后验证 + 前后一致性对比")
    print("=" * 65)

    sp = snapshot_path(tag)
    if not os.path.exists(sp):
        print(f"❌ 找不到快照文件 {sp}，请先执行 --step1")
        return 1
    with open(sp, "r", encoding="utf-8") as f:
        snap_before = json.load(f)
    m = snap_before["meta"]
    print(f"  从快照读取批次 id={m['batch_id']}, no={m['batch_no']}")

    # 重启后采集
    print(f"\n[重启后验证]")
    snap_after = build_snapshot(
        m["batch_id"], m["bid_a"], m["bid_b"],
        m["bno_a"], m["bno_b"], m["batch_no"], m["cancel_reason"]
    )
    snap_after["meta"]["tag_ref"] = tag
    r2 = verify_snapshot(snap_after, "重启后")

    # 一致性对比
    print(f"\n[重启前后一致性对比]")
    r3 = []
    sb = snap_before["detail"]
    sa = snap_after["detail"]
    r3.append(check("对比 详情桶数", sb["barrel_count"] == sa["barrel_count"],
                    f"{sb['barrel_count']} vs {sa['barrel_count']}"))
    sb_ids = sorted([b["id"] for b in sb["barrels"]])
    sa_ids = sorted([b["id"] for b in sa["barrels"]])
    r3.append(check("对比 详情桶ID列表", sb_ids == sa_ids, f"{sb_ids} vs {sa_ids}"))
    sb_nos = sorted([b["barrel_no"] for b in sb["barrels"]])
    sa_nos = sorted([b["barrel_no"] for b in sa["barrels"]])
    r3.append(check("对比 详情桶号列表", sb_nos == sa_nos, f"{sb_nos} vs {sa_nos}"))
    for key in ["status", "batch_no", "total_weight_kg", "cancel_reason",
                "cancelled_by_role", "cancelled_by_name", "cancelled_at",
                "created_by_role", "created_by_name", "created_at",
                "vehicle_no", "driver_name", "manifest_no"]:
        r3.append(check(f"对比 详情.{key}", sb.get(key) == sa.get(key),
                        f"'{sb.get(key)}' vs '{sa.get(key)}'"))

    r3.append(check("对比 列表API桶数",
                    snap_before["list_barrel_count"] == snap_after["list_barrel_count"],
                    f"{snap_before['list_barrel_count']} vs {snap_after['list_barrel_count']}"))

    jeb = snap_before["json_export"]
    jea = snap_after["json_export"]
    if jeb and jea:
        r3.append(check("对比 JSON导出桶数", jeb["barrel_count"] == jea["barrel_count"]))
        jeb_ids = sorted([b["barrel_id"] for b in jeb["barrels"]])
        jea_ids = sorted([b["barrel_id"] for b in jea["barrels"]])
        r3.append(check("对比 JSON导出桶ID", jeb_ids == jea_ids, f"{jeb_ids} vs {jea_ids}"))
        for key in ["status", "batch_no", "total_weight_kg", "cancel_reason",
                    "cancelled_by_role", "cancelled_by_name", "cancelled_at",
                    "manifest_no", "vehicle_no", "driver_name"]:
            r3.append(check(f"对比 JSON导出.{key}", jeb.get(key) == jea.get(key),
                            f"'{jeb.get(key)}' vs '{jea.get(key)}'"))

    r3.append(check("对比 CSV导出(逐字符)",
                    snap_before["csv_text"] == snap_after["csv_text"],
                    "完全相同" if snap_before["csv_text"] == snap_after["csv_text"] else "有差异"))

    for k in ["status", "transport_batch_id"]:
        r3.append(check(f"对比 桶A.{k}",
                        snap_before["barrel_a"].get(k) == snap_after["barrel_a"].get(k),
                        f"{snap_before['barrel_a'].get(k)} vs {snap_after['barrel_a'].get(k)}"))
        r3.append(check(f"对比 桶B.{k}",
                        snap_before["barrel_b"].get(k) == snap_after["barrel_b"].get(k),
                        f"{snap_before['barrel_b'].get(k)} vs {snap_after['barrel_b'].get(k)}"))

    # 汇总
    print("\n" + "=" * 65)
    all_r = r2 + r3
    passed = sum(all_r)
    total = len(all_r)
    print(f"Step2 汇总: {passed}/{total} 通过")
    print(f"  重启后独立验证:   {sum(r2)}/{len(r2)}")
    print(f"  重启前后一致性对比: {sum(r3)}/{len(r3)}")
    print("=" * 65)

    try:
        os.remove(sp)
    except Exception:
        pass

    return 0 if passed == total else 1


def main():
    if len(sys.argv) < 2:
        print("用法:")
        print(f"  python {sys.argv[0]} <标签> --step1   (建数据+取消+快照)")
        print(f"  python {sys.argv[0]} <标签> --step2   (重启后验证+对比)")
        print(f"例: python {sys.argv[0]} TEST01 --step1")
        return 1

    tag = sys.argv[1]
    mode = sys.argv[2] if len(sys.argv) > 2 else "--step1"

    if mode == "--step1":
        return run_step1(tag)
    elif mode == "--step2":
        return run_step2(tag)
    else:
        print(f"未知模式 {mode}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
