# -*- coding: utf-8 -*-
"""
转运批次取消追溯问题 - 环境自洽版测试脚本

特性：
  * 不依赖任何残留数据，首次运行也能稳定复现
  * 自动检查服务是否启动，未启动则等待或提示
  * 自动查询有容量的库位（避开占满的库位）
  * 桶号/批次号自带时间戳，永不冲突
  * 先跑"复现模式"（模拟修复前状态，验证bug存在）
  * 再跑"修复后验证"（确认bug已修）
  * 所有校验直接核对用户可见字段（桶数/桶号/状态/原因）

运行方式：
  # 1. 先模拟修复前复现（如果代码还没修，会看到bug）
  python test_batch_cancel_robust.py --mode repro

  # 2. 代码修复后，验证修复有效
  python test_batch_cancel_robust.py --mode verify

  # 3. 服务重启一致性验证（需要先执行 --mode verify 生成快照）
  #    手动重启服务后再执行：
  python test_batch_cancel_robust.py --mode restart

输出：直接打印真实请求/响应和核对结果，所有结论可复现
"""
import requests
import json
import sys
import os
import time
import random
import string

BASE = "http://localhost:5000"
API = BASE + "/api/v1"
SNAPSHOT_FILE = "cancel_trace_snapshot.json"


def random_tag(n=6):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=n))


def wait_service(timeout=60):
    print(f"  等待服务启动（最多 {timeout}s）...")
    for i in range(timeout):
        try:
            r = requests.get(f"{BASE}/health", timeout=2)
            if r.status_code == 200:
                print(f"  ✅ 服务已启动，耗时 {i}s")
                return True
        except Exception:
            pass
        time.sleep(1)
    print(f"  ❌ 服务未启动，请先运行: python run.py")
    return False


def POST(path, data, expect=200, verbose=True):
    url = API + path
    r = requests.post(url, json=data, timeout=10)
    if verbose:
        print(f"    POST {path} -> {r.status_code}", end="")
    if r.status_code != expect and verbose:
        print(f" | 响应: {r.text[:300]}")
    elif verbose:
        print()
    return r.status_code, (r.json() if r.text else {})


def GET(path, verbose=True):
    url = API + path
    r = requests.get(url, timeout=10)
    if verbose:
        print(f"    GET {path} -> {r.status_code}")
    return r.status_code, (r.json() if r.text else {})


def GET_CSV(path, verbose=True):
    url = API + path
    r = requests.get(url, timeout=10)
    if verbose:
        print(f"    GET {path} -> {r.status_code}")
    return r.status_code, r.text


def check(name, cond, detail=""):
    mark = "✅" if cond else "❌"
    print(f"    {mark} {name}: {'通过' if cond else '失败'} {detail}")
    return cond


def find_available_location(required_kg=500):
    """找到一个有足够剩余容量的库位"""
    code, locs = GET("/locations", verbose=False)
    if code != 200 or not isinstance(locs, list):
        raise RuntimeError(f"无法查询库位: {locs}")
    # 优先选容量大且有剩余的
    candidates = []
    for loc in locs:
        if not loc.get("is_active"):
            continue
        cap = loc.get("max_capacity_kg", loc.get("capacity_kg", 0))
        used = loc.get("current_usage_kg", 0)
        remaining = cap - used
        if remaining >= required_kg:
            candidates.append((remaining, loc))
    if not candidates:
        raise RuntimeError(f"没有库位剩余容量 ≥ {required_kg}kg，请先清理或增加库位")
    # 选剩余最多的
    candidates.sort(reverse=True)
    best = candidates[0][1]
    cap = best.get("max_capacity_kg", best.get("capacity_kg", 0))
    used = best.get("current_usage_kg", 0)
    print(f"    自动选择库位: {best['code']} (容量 {cap}kg, 已用 {used}kg, 剩余 {cap - used}kg)")
    return best["id"], best["code"]


def find_category_by_code(code="HW12"):
    code, cats = GET("/categories", verbose=False)
    if code != 200 or not isinstance(cats, list):
        raise RuntimeError(f"无法查询类别")
    for c in cats:
        if c.get("code") == code and c.get("is_active"):
            return c["id"]
    # fallback 找第一个激活的
    for c in cats:
        if c.get("is_active"):
            return c["id"]
    raise RuntimeError("找不到可用的危废类别")


def create_barrel_full(tag, weight, loc_id):
    """创建→称重→复核，返回桶ID和桶号"""
    barrel_no = f"TRACE-{tag}"
    print(f"    创建桶 {barrel_no} ({weight}kg)...")
    c, data = POST("/barrels", {
        "barrel_no": barrel_no,
        "waste_category_id": find_category_by_code(),
        "operator_role": "WORKSHOP",
        "operator_name": "车间张工"
    }, 201)
    if c != 201 or not data or "id" not in data:
        raise RuntimeError(f"创建桶失败: {data}")
    bid = data["id"]
    POST(f"/barrels/{bid}/weigh", {
        "weight_kg": weight,
        "storage_location_id": loc_id,
        "tag_code": f"TAG-{barrel_no}",
        "operator_role": "WAREHOUSE",
        "operator_name": "仓管老李"
    })
    POST(f"/barrels/{bid}/review", {
        "operator_role": "ENV_AUDITOR",
        "operator_name": "复核老王",
        "notes": "包装完好，标识清晰"
    })
    return bid, barrel_no


def get_batch_export_batch(json_export, batch_id):
    """从导出数据中定位目标批次"""
    batches = json_export.get("batches", []) if isinstance(json_export, dict) else []
    for b in batches:
        if b.get("id") == batch_id:
            return b
    return None


def verify_batch(batch_id, exp_barrel_ids, exp_barrel_nos, exp_status, exp_cancel_reason,
                 exp_total_weight, label):
    """
    直接核对用户可见字段（详情/列表/JSON/CSV 四处）
    """
    results = []
    print(f"\n  --- {label} 核对 ---")

    # 1. 详情接口
    _, detail = GET(f"/batches/{batch_id}")
    detail_ids = sorted([b["id"] for b in detail.get("barrels", [])])
    detail_nos = sorted([b["barrel_no"] for b in detail.get("barrels", [])])

    print(f"    详情接口字段:")
    print(f"      barrel_count    = {detail.get('barrel_count')}")
    print(f"      barrel_ids      = {detail_ids}")
    print(f"      barrel_nos      = {detail_nos}")
    print(f"      status          = {detail.get('status')}")
    print(f"      cancel_reason   = {detail.get('cancel_reason')}")
    print(f"      total_weight_kg = {detail.get('total_weight_kg')}")

    results.append(check(f"详情桶数量={len(exp_barrel_ids)}",
                         detail.get("barrel_count") == len(exp_barrel_ids),
                         f"实际={detail.get('barrel_count')}"))
    results.append(check("详情桶ID正确",
                         detail_ids == sorted(exp_barrel_ids),
                         f"预期={sorted(exp_barrel_ids)}, 实际={detail_ids}"))
    results.append(check("详情桶号正确",
                         detail_nos == sorted(exp_barrel_nos),
                         f"预期={sorted(exp_barrel_nos)}, 实际={detail_nos}"))
    results.append(check(f"详情状态={exp_status}",
                         detail.get("status") == exp_status,
                         f"实际={detail.get('status')}"))
    if exp_cancel_reason:
        results.append(check("详情取消原因正确",
                             detail.get("cancel_reason") == exp_cancel_reason,
                             f"预期='{exp_cancel_reason}', 实际='{detail.get('cancel_reason')}'"))
    results.append(check(f"详情总重量={exp_total_weight}",
                         detail.get("total_weight_kg") == exp_total_weight,
                         f"实际={detail.get('total_weight_kg')}"))

    # 2. 列表接口
    _, blist = GET("/batches", verbose=False)
    binlist = next((b for b in blist if b["id"] == batch_id), None)
    list_count = binlist.get("barrel_count") if binlist else None
    results.append(check(f"列表API barrel_count={len(exp_barrel_ids)}",
                         list_count == len(exp_barrel_ids),
                         f"实际={list_count}"))

    # 3. JSON 导出
    _, jexp_raw = GET("/batches/export/json", verbose=False)
    jb = get_batch_export_batch(jexp_raw, batch_id)
    if jb:
        jids = sorted([b.get("barrel_id") for b in jb.get("barrels", [])])
        jnos = sorted([b.get("barrel_no") for b in jb.get("barrels", [])])
        print(f"    JSON导出字段:")
        print(f"      barrel_count    = {jb.get('barrel_count')}")
        print(f"      barrel_ids      = {jids}")
        print(f"      barrel_nos      = {jnos}")
        print(f"      status          = {jb.get('status')}")
        print(f"      cancel_reason   = {jb.get('cancel_reason')}")
        print(f"      total_weight_kg = {jb.get('total_weight_kg')}")
        results.append(check(f"JSON导出桶数量={len(exp_barrel_ids)}",
                             jb.get("barrel_count") == len(exp_barrel_ids),
                             f"实际={jb.get('barrel_count')}"))
        results.append(check("JSON导出桶ID正确",
                             jids == sorted(exp_barrel_ids),
                             f"预期={sorted(exp_barrel_ids)}, 实际={jids}"))
        results.append(check("JSON导出桶号正确",
                             jnos == sorted(exp_barrel_nos),
                             f"预期={sorted(exp_barrel_nos)}, 实际={jnos}"))
        results.append(check(f"JSON导出状态={exp_status}",
                             jb.get("status") == exp_status,
                             f"实际={jb.get('status')}"))
        if exp_cancel_reason:
            results.append(check("JSON导出取消原因正确",
                                 jb.get("cancel_reason") == exp_cancel_reason,
                                 f"预期='{exp_cancel_reason}', 实际='{jb.get('cancel_reason')}'"))
        results.append(check(f"JSON导出总重量={exp_total_weight}",
                             jb.get("total_weight_kg") == exp_total_weight,
                             f"实际={jb.get('total_weight_kg')}"))
    else:
        results.append(check("JSON导出存在目标批次", False))

    # 4. CSV 导出
    _, csv_text = GET_CSV("/batches/export/csv", verbose=False)
    lines = csv_text.strip().split("\n")
    target_line = None
    batch_no_in_detail = detail.get("batch_no", "")
    for line in lines[1:]:
        cols = line.split(",")
        if len(cols) > 0 and cols[0].strip() == batch_no_in_detail:
            target_line = line
            break
    if target_line:
        cols = target_line.split(",")
        print(f"    CSV导出行 (第1列批次号={cols[0].strip()}):")
        print(f"      桶数量列(col8)  = {cols[7].strip() if len(cols) > 7 else '?'}")
        print(f"      状态列(col10)   = {cols[9].strip() if len(cols) > 9 else '?'}")
        print(f"      取消原因列(col11) = {cols[10].strip() if len(cols) > 10 else '?'}")
        results.append(check("CSV存在目标批次行", True))
        results.append(check(f"CSV桶数量列={len(exp_barrel_ids)}",
                             len(cols) > 7 and str(len(exp_barrel_ids)) in cols[7].strip(),
                             f"cols[7]={cols[7].strip() if len(cols) > 7 else '?'}"))
        results.append(check(f"CSV状态列={exp_status}",
                             len(cols) > 9 and exp_status in cols[9].strip(),
                             f"cols[9]={cols[9].strip() if len(cols) > 9 else '?'}"))
        if exp_cancel_reason:
            results.append(check("CSV取消原因列正确",
                                 len(cols) > 10 and cols[10].strip() == exp_cancel_reason,
                                 f"预期='{exp_cancel_reason}', 实际='{cols[10].strip() if len(cols) > 10 else '?'}"))
        # 桶号都在该行中
        for bno in exp_barrel_nos:
            results.append(check(f"CSV包含桶号 {bno}",
                                 bno in target_line,
                                 f"出现={bno in target_line}"))
    else:
        results.append(check("CSV中找到目标批次行", False, f"搜索批次号={batch_no_in_detail}"))

    # 5. 桶自身状态（不能被修改带坏）
    print(f"    桶状态核对（确认恢复逻辑没被带坏）:")
    # 根据当前阶段判断预期状态
    if label.startswith("取消前"):
        expected_status = "BATCHED"
        expected_batch_id_not_none = True
    else:  # 取消后
        expected_status = "REVIEWED"
        expected_batch_id_not_none = False
    for bid, bno in zip(exp_barrel_ids, exp_barrel_nos):
        _, bd = GET(f"/barrels/{bid}", verbose=False)
        st = bd.get("status")
        tbid = bd.get("transport_batch_id")
        print(f"      桶 {bno}: status={st}, transport_batch_id={tbid}")
        results.append(check(f"桶 {bno} 状态={expected_status}", st == expected_status, f"实际={st}"))
        if expected_batch_id_not_none:
            results.append(check(f"桶 {bno} batch_id≠None", tbid is not None, f"实际={tbid}"))
        else:
            results.append(check(f"桶 {bno} batch_id=None", tbid is None, f"实际={tbid}"))

    return results


def run_scenario(tag, expect_cancelled_visible, skip_rebatch=False):
    """
    完整场景：建2桶 → 合批 → 取消 → 验证
    expect_cancelled_visible: True=修复后（能看到数据）, False=修复前（看不到数据）
    skip_rebatch: 如果为 True，跳过最后的"重新合批"验证（用于重启测试前置步骤，保持桶状态稳定）
    """
    print(f"\n{'=' * 70}")
    print(f"场景: {tag}")
    print(f"{'=' * 70}")

    if not wait_service():
        return 1, []

    # 准备
    weight_a, weight_b = 180.0, 210.5
    total_weight = weight_a + weight_b
    loc_id, loc_code = find_available_location(weight_a + weight_b + 50)
    run_tag = random_tag(6)
    cancel_reason = f"取消追溯测试-{run_tag}"
    batch_no = f"BATCH-TRACE-{run_tag}"

    print(f"  测试标签: {run_tag}")
    print(f"  两个桶: {weight_a}kg + {weight_b}kg = {total_weight}kg")
    print(f"  取消原因: {cancel_reason}")
    print(f"  批次号: {batch_no}")

    # 1. 建桶
    print(f"\n  [1/4] 准备两个已复核桶")
    bid_a, bno_a = create_barrel_full(run_tag + "-A", weight_a, loc_id)
    bid_b, bno_b = create_barrel_full(run_tag + "-B", weight_b, loc_id)
    exp_ids = [bid_a, bid_b]
    exp_nos = [bno_a, bno_b]
    print(f"    桶A: id={bid_a}, no={bno_a}")
    print(f"    桶B: id={bid_b}, no={bno_b}")

    # 2. 合批
    print(f"\n  [2/4] 运输员创建转运批次")
    _, batch = POST("/batches", {
        "batch_no": batch_no,
        "vehicle_no": f"京A-{run_tag}",
        "driver_name": "钱司机",
        "driver_phone": "13900000001",
        "expected_exit_time": "2026-06-30T14:00:00",
        "manifest_no": f"HB-TRACE-{run_tag}",
        "barrel_ids": exp_ids,
        "operator_role": "TRANSPORT",
        "operator_name": "钱司机"
    }, 201)
    batch_id = batch["id"]
    print(f"    批次已创建: id={batch_id}")

    # 3. 取消前验证（PENDING 状态应该看到数据）
    print(f"\n  [3/4] 取消前（PENDING）验证")
    r_before = verify_batch(
        batch_id=batch_id,
        exp_barrel_ids=exp_ids,
        exp_barrel_nos=exp_nos,
        exp_status="PENDING",
        exp_cancel_reason=None,
        exp_total_weight=total_weight,
        label="取消前(PENDING)"
    )

    # 4. 取消批次
    print(f"\n  [4/4] 取消批次")
    POST(f"/batches/{batch_id}/cancel", {
        "cancel_reason": cancel_reason,
        "operator_role": "ENV_AUDITOR",
        "operator_name": "复核老王"
    })
    print(f"    已取消")

    # 5. 取消后验证
    print(f"\n  [5/5] 取消后（CANCELLED）验证 {'(预期有数据)' if expect_cancelled_visible else '(预期空 - bug复现)'}")
    r_after = verify_batch(
        batch_id=batch_id,
        exp_barrel_ids=exp_ids if expect_cancelled_visible else [],
        exp_barrel_nos=exp_nos if expect_cancelled_visible else [],
        exp_status="CANCELLED",
        exp_cancel_reason=cancel_reason,
        exp_total_weight=total_weight,
        label="取消后(CANCELLED)"
    )

    # 6. 验证取消后可重新合批（不破坏现有逻辑）
    if not skip_rebatch:
        print(f"\n  [6/6] 验证取消后可重新合批（确认恢复逻辑）")
        re_batch_no = f"BATCH-TRACE-RE-{run_tag}"
        rc, _ = POST("/batches", {
            "batch_no": re_batch_no,
            "vehicle_no": f"京A-RE{run_tag}",
            "driver_name": "钱司机",
            "expected_exit_time": "2026-06-30T16:00:00",
            "manifest_no": f"HB-TRACE-RE-{run_tag}",
            "barrel_ids": exp_ids,
            "operator_role": "TRANSPORT",
            "operator_name": "钱司机"
        }, 201)
        r_rebatch = [check("取消后可重新合批成功", rc == 201, f"响应码={rc}")]
    else:
        print(f"\n  [6/6] 跳过重新合批（保持桶状态稳定，用于重启验证前置）")
        r_rebatch = []

    # 汇总
    all_r = r_before + r_after + r_rebatch
    passed = sum(all_r)
    total = len(all_r)

    print(f"\n" + "=" * 70)
    print(f"场景 '{tag}' 汇总: {passed}/{total} 通过")
    print(f"  取消前(PENDING):   {sum(r_before)}/{len(r_before)}")
    print(f"  取消后(CANCELLED): {sum(r_after)}/{len(r_after)} {'← BUG已复现（桶数据丢失）' if expect_cancelled_visible is False and sum(r_after) < len(r_after) else ''}")
    print(f"  重新合批:          {sum(r_rebatch)}/{len(r_rebatch)}")
    print("=" * 70)

    # 返回用于重启对比的关键数据
    snapshot = {
        "batch_id": batch_id,
        "exp_barrel_ids": exp_ids,
        "exp_barrel_nos": exp_nos,
        "cancel_reason": cancel_reason,
        "total_weight": total_weight,
        "verify_result": "pass" if sum(all_r) == len(all_r) else "fail",
        "detail_before": None,  # 重启对比会重新取
    }

    return 0 if sum(all_r) == len(all_r) else 1, snapshot


def run_verify_restart():
    """Step2：重启后加载快照并对比"""
    if not os.path.exists(SNAPSHOT_FILE):
        print(f"❌ 找不到快照文件 {SNAPSHOT_FILE}")
        print("  请先执行: python test_batch_cancel_robust.py --mode verify")
        return 1

    with open(SNAPSHOT_FILE, "r", encoding="utf-8") as f:
        snap_before = json.load(f)

    print(f"\n{'=' * 70}")
    print("重启后一致性验证")
    print(f"{'=' * 70}")
    if not wait_service():
        return 1

    print(f"  从快照加载: 批次id={snap_before['batch_id']}")
    print(f"  预期桶: ids={snap_before['exp_barrel_ids']}, nos={snap_before['exp_barrel_nos']}")

    # 重启后验证（不核对桶当前状态（因为快照后桶可能被重新合批属正常业务），只核对批次追溯数据
    print(f"\n  --- 重启后(CANCELLED) 核对 ---")
    r = []
    _, detail = GET(f"/batches/{snap_before['batch_id']}")
    detail_ids = sorted([b["id"] for b in detail.get("barrels", [])])
    detail_nos = sorted([b["barrel_no"] for b in detail.get("barrels", [])])
    exp_ids = sorted(snap_before["exp_barrel_ids"])
    exp_nos = sorted(snap_before["exp_barrel_nos"])

    print(f"    详情接口:")
    print(f"      barrel_count    = {detail.get('barrel_count')}")
    print(f"      barrel_ids      = {detail_ids}")
    print(f"      barrel_nos      = {detail_nos}")
    print(f"      status          = {detail.get('status')}")
    print(f"      cancel_reason   = {detail.get('cancel_reason')}")
    print(f"      total_weight_kg = {detail.get('total_weight_kg')}")

    r.append(check("重启后-详情桶数量=2", detail.get("barrel_count") == 2, f"实际={detail.get('barrel_count')}"))
    r.append(check("重启后-详情桶ID正确", detail_ids == exp_ids, f"{detail_ids} vs {exp_ids}"))
    r.append(check("重启后-详情桶号正确", detail_nos == exp_nos, f"{detail_nos} vs {exp_nos}"))
    r.append(check("重启后-详情状态=CANCELLED", detail.get("status") == "CANCELLED"))
    r.append(check("重启后-详情取消原因正确", detail.get("cancel_reason") == snap_before["cancel_reason"], f"'{detail.get('cancel_reason')}' vs '{snap_before['cancel_reason']}'"))
    r.append(check("重启后-详情总重量正确", detail.get("total_weight_kg") == snap_before["total_weight"], f"{detail.get('total_weight_kg')} vs {snap_before['total_weight']}"))

    _, blist = GET("/batches", verbose=False)
    binlist = next((b for b in blist if b["id"] == snap_before["batch_id"]), None)
    list_count = binlist.get("barrel_count") if binlist else None

    r.append(check("重启后-列表API barrel_count=2", list_count == 2, f"实际={list_count}"))

    _, jexp_raw = GET("/batches/export/json", verbose=False)
    jb = get_batch_export_batch(jexp_raw, snap_before["batch_id"])
    if jb:
        jids = sorted([b.get("barrel_id") for b in jb.get("barrels", [])])
        jnos = sorted([b.get("barrel_no") for b in jb.get("barrels", [])])
        print(f"    JSON导出:")
        print(f"      barrel_count    = {jb.get('barrel_count')}")
        print(f"      barrel_ids      = {jids}")
        print(f"      barrel_nos      = {jnos}")
        print(f"      status          = {jb.get('status')}")
        print(f"      cancel_reason   = {jb.get('cancel_reason')}")
        print(f"      total_weight_kg = {jb.get('total_weight_kg')}")
        r.append(check("重启后-JSON导出桶数量=2", jb.get("barrel_count") == 2))
        r.append(check("重启后-JSON导出桶ID正确", jids == exp_ids, f"{jids} vs {exp_ids}"))
        r.append(check("重启后-JSON导出桶号正确", jnos == exp_nos, f"{jnos} vs {exp_nos}"))
        r.append(check("重启后-JSON导出状态=CANCELLED", jb.get("status") == "CANCELLED"))
        r.append(check("重启后-JSON导出取消原因正确", jb.get("cancel_reason") == snap_before["cancel_reason"]))
        r.append(check("重启后-JSON导出总重量正确", jb.get("total_weight_kg") == snap_before["total_weight"]))
    else:
        r.append(check("重启后-JSON导出批次存在", False))

    _, csv_text = GET_CSV("/batches/export/csv", verbose=False)
    lines = csv_text.strip().split("\n")
    target_line = None
    snap_batch_no = snap_before["detail"]["batch_no"]
    snap_cancel_reason = snap_before["detail"]["cancel_reason"]
    snap_exp_barrel_nos = snap_before["exp_barrel_nos"]
    for line in lines[1:]:
        cols = line.split(",")
        if len(cols) > 0 and cols[0].strip() == snap_batch_no:
            target_line = line
            break
    if target_line:
        cols = target_line.split(",")
        col8 = cols[7].strip() if len(cols) > 7 else "?"
        col10 = cols[9].strip() if len(cols) > 9 else "?"
        col11 = cols[10].strip() if len(cols) > 10 else "?"
        print(f"    CSV导出:")
        print(f"      桶数量列(col8)  = {col8}")
        print(f"      状态列(col10)   = {col10}")
        print(f"      取消原因列(col11) = {col11}")
        r.append(check("重启后-CSV批次行存在", True))
        r.append(check("重启后-CSV桶数量列=2", len(cols) > 7 and "2" in cols[7].strip()))
        r.append(check("重启后-CSV状态列=CANCELLED", len(cols) > 9 and "CANCELLED" in cols[9].strip()))
        r.append(check("重启后-CSV取消原因列正确", len(cols) > 10 and cols[10].strip() == snap_cancel_reason))
        for bno in snap_exp_barrel_nos:
            r.append(check(f"重启后-CSV包含桶号 {bno}", bno in target_line))
    else:
        r.append(check("重启后-CSV批次行存在", False))

    # 取详情字段与快照对比
    _, detail_after = GET(f"/batches/{snap_before['batch_id']}", verbose=False)
    _, jexp_after_raw = GET("/batches/export/json", verbose=False)
    _, csv_after = GET_CSV("/batches/export/csv", verbose=False)
    jb_after = get_batch_export_batch(jexp_after_raw, snap_before["batch_id"])

    # 保存当前快照用于对比
    snap_after = {
        "detail": detail_after,
        "json_export_batch": jb_after,
        "csv_text": csv_after,
    }

    # 逐字段对比
    print(f"\n  --- 重启前后逐字段一致性对比 ---")
    compare_results = []
    sb_d = snap_before.get("detail", {}) if isinstance(snap_before, dict) and "detail" in snap_before else detail_after
    sa_d = detail_after

    for key in ["barrel_count", "status", "batch_no", "total_weight_kg",
                "cancel_reason", "cancelled_by_role", "cancelled_by_name",
                "cancelled_at", "created_by_role", "created_by_name",
                "created_at", "vehicle_no", "driver_name", "manifest_no"]:
        sv = sb_d.get(key) if isinstance(sb_d, dict) else None
        av = sa_d.get(key)
        compare_results.append(check(f"详情.{key}", sv == av, f"'{sv}' vs '{av}'"))

    sb_ids = sorted([b["id"] for b in (sb_d.get("barrels", []) if isinstance(sb_d, dict) else [])])
    sa_ids = sorted([b["id"] for b in sa_d.get("barrels", [])])
    compare_results.append(check("详情.barrels.id列表", sb_ids == sa_ids, f"{sb_ids} vs {sa_ids}"))

    sb_nos = sorted([b["barrel_no"] for b in (sb_d.get("barrels", []) if isinstance(sb_d, dict) else [])])
    sa_nos = sorted([b["barrel_no"] for b in sa_d.get("barrels", [])])
    compare_results.append(check("详情.barrels.barrel_no列表", sb_nos == sa_nos, f"{sb_nos} vs {sa_nos}"))

    if snap_before.get("json_export_batch") and snap_after.get("json_export_batch"):
        sjb = snap_before["json_export_batch"]
        ajb = snap_after["json_export_batch"]
        compare_results.append(check("JSON导出.barrel_count", sjb.get("barrel_count") == ajb.get("barrel_count"),
                                     f"{sjb.get('barrel_count')} vs {ajb.get('barrel_count')}"))
        sjb_ids = sorted([b.get("barrel_id") for b in sjb.get("barrels", [])])
        ajb_ids = sorted([b.get("barrel_id") for b in ajb.get("barrels", [])])
        compare_results.append(check("JSON导出.barrels.id列表", sjb_ids == ajb_ids,
                                     f"{sjb_ids} vs {ajb_ids}"))
        for key in ["status", "batch_no", "total_weight_kg", "cancel_reason"]:
            compare_results.append(check(f"JSON导出.{key}", sjb.get(key) == ajb.get(key),
                                         f"'{sjb.get(key)}' vs '{ajb.get(key)}'"))

    if snap_before.get("csv_text") and snap_after.get("csv_text"):
        compare_results.append(check("CSV导出(逐字符)",
                                     snap_before["csv_text"] == snap_after["csv_text"],
                                     "完全相同" if snap_before["csv_text"] == snap_after["csv_text"] else "有差异"))

    all_r = r + compare_results
    passed = sum(all_r)
    total = len(all_r)
    print(f"\n{'=' * 70}")
    print(f"重启后汇总: {passed}/{total} 通过")
    print(f"  重启后独立验证: {sum(r)}/{len(r)}")
    print(f"  重启前后对比:   {sum(compare_results)}/{len(compare_results)}")
    print(f"{'=' * 70}")

    try:
        os.remove(SNAPSHOT_FILE)
    except Exception:
        pass

    return 0 if passed == total else 1


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "verify"

    if mode == "--help" or mode == "-h":
        print(__doc__)
        return 0

    if mode == "repro" or mode == "--mode repro":
        # 复现模式（假设代码还没修复，验证bug存在）
        print("=" * 70)
        print("【复现模式】模拟修复前代码，预期 CANCELLED 后桶数据为空")
        print("=" * 70)
        exit_code, _ = run_scenario("复现BUG-取消后追溯丢失", expect_cancelled_visible=False)
        return exit_code

    elif mode == "verify" or mode == "--mode verify":
        # 修复后验证模式
        print("=" * 70)
        print("【修复验证模式】代码已修复，CANCELLED 后应保留完整数据")
        print("=" * 70)
        exit_code, snapshot = run_scenario("修复后-取消后追溯正常", expect_cancelled_visible=True, skip_rebatch=True)
        if exit_code == 0:
            # 保存快照供重启对比
            _, detail = GET(f"/batches/{snapshot['batch_id']}", verbose=False)
            _, jexp_raw = GET("/batches/export/json", verbose=False)
            _, csv_text = GET_CSV("/batches/export/csv", verbose=False)
            jb = get_batch_export_batch(jexp_raw, snapshot["batch_id"])
            snapshot["detail"] = detail
            snapshot["json_export_batch"] = jb
            snapshot["csv_text"] = csv_text
            with open(SNAPSHOT_FILE, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, ensure_ascii=False, indent=2, default=str)
            print(f"\n✅ 快照已保存到 {SNAPSHOT_FILE}")
            print("   现在可以重启服务，然后执行:")
            print(f"     python {sys.argv[0]} --mode restart")
        return exit_code

    elif mode == "restart" or mode == "--mode restart":
        return run_verify_restart()

    else:
        print(f"未知模式: {mode}")
        print(__doc__)
        return 1


if __name__ == "__main__":
    sys.exit(main())
