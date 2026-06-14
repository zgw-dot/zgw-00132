# 危废暂存转移 JSON API

本地危废暂存转移管理系统，管理危废桶从车间入库、称重、环保复核、装车转移到撤销的完整链路。

## 技术栈

- Python 3.9+
- Flask 3.0
- Flask-SQLAlchemy
- SQLite（本地文件数据库）
- Marshmallow（参数校验）

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 启动服务

```bash
python run.py
```

服务启动在 `http://localhost:5000`

### 3. 健康检查

```bash
curl http://localhost:5000/health
```

## 系统角色与状态流转

### 角色定义

| 角色 | 英文标识 | 权限 |
|------|----------|------|
| 车间 | WORKSHOP | 创建危废桶 |
| 仓管 | WAREHOUSE | 称重入库、撤销 |
| 环保复核员 | ENV_AUDITOR | 复核、撤销 |
| 运输员 | TRANSPORT | 装车转移 |

### 状态流转

```
CREATED (已创建)
    ↓ (仓管称重入库)
WEIGHED (已称重入库)
    ↓ (环保复核)
REVIEWED (已复核)
    ↓ (运输员装车)
LOADED (已装车转移)
```

任意非终态均可由仓管或环保复核员执行撤销 → `CANCELLED`

## 预置样例数据

### 危废类别（2类）

| 编码 | 名称 |
|------|------|
| HW08 | 废矿物油 |
| HW12 | 染料涂料废物 |

### 库位（2个）

| 编码 | 名称 | 最大容量 | 允许类别 |
|------|------|----------|----------|
| STORE-A | A库区-矿物油暂存区 | 5000kg | HW08 |
| STORE-B | B库区-涂料废物暂存区 | 3000kg | HW12 |

> **说明**：容量校验和类别筛选基于数据库动态配置，非写死逻辑。可通过添加更多库位和类别灵活扩展。

## API 接口文档

### 基础信息

```bash
# 查看系统信息
curl http://localhost:5000/

# 查看系统状态（角色、状态、权限矩阵）
curl http://localhost:5000/api/v1/status

# 查看危废类别
curl http://localhost:5000/api/v1/categories

# 查看库位
curl http://localhost:5000/api/v1/locations
```

---

## 正常验收链路（curl 样例）

### 步骤1: 车间创建危废桶

```bash
curl -X POST http://localhost:5000/api/v1/barrels \
  -H "Content-Type: application/json" \
  -d '{
    "barrel_no": "B-2024-0001",
    "waste_category_id": 1,
    "operator_role": "WORKSHOP",
    "operator_name": "张工"
  }'
```

**响应**：返回桶信息，状态为 `CREATED`

### 步骤2: 仓管称重入库

```bash
curl -X POST http://localhost:5000/api/v1/barrels/1/weigh \
  -H "Content-Type: application/json" \
  -d '{
    "weight_kg": 250.5,
    "storage_location_id": 1,
    "tag_code": "TAG-HW08-0001",
    "operator_role": "WAREHOUSE",
    "operator_name": "李仓管"
  }'
```

**响应**：状态更新为 `WEIGHED`，记录重量、库位、标签码

### 步骤3: 环保复核员复核

```bash
curl -X POST http://localhost:5000/api/v1/barrels/1/review \
  -H "Content-Type: application/json" \
  -d '{
    "operator_role": "ENV_AUDITOR",
    "operator_name": "王复核",
    "notes": "危废标识清晰，包装完好"
  }'
```

**响应**：状态更新为 `REVIEWED`

### 步骤4: 运输员装车转移

```bash
curl -X POST http://localhost:5000/api/v1/barrels/1/load \
  -H "Content-Type: application/json" \
  -d '{
    "manifest_no": "HB-LD-2024-0001",
    "operator_role": "TRANSPORT",
    "operator_name": "赵司机"
  }'
```

**响应**：状态更新为 `LOADED`，记录联单号

### 步骤5: 导出审计记录

```bash
# JSON 格式导出
curl http://localhost:5000/api/v1/audit/export/json

# CSV 格式导出
curl http://localhost:5000/api/v1/audit/export/csv -o audit_export.csv
```

---

## 转运批次完整验收链路（两个桶合批，curl 样例）

### 前置准备: 创建并复核两个危废桶

```bash
# === 桶 A: HW12 类别，250.5kg ===
# 车间创建
curl -X POST http://localhost:5000/api/v1/barrels \
  -H "Content-Type: application/json" \
  -d '{
    "barrel_no": "B-BATCH-DEMO-A",
    "waste_category_id": 2,
    "operator_role": "WORKSHOP",
    "operator_name": "张工"
  }'

# 仓管称重入库（假设返回id=1）
curl -X POST http://localhost:5000/api/v1/barrels/1/weigh \
  -H "Content-Type: application/json" \
  -d '{
    "weight_kg": 250.5,
    "storage_location_id": 2,
    "tag_code": "TAG-BATCH-DEMO-A",
    "operator_role": "WAREHOUSE",
    "operator_name": "李仓管"
  }'

# 环保复核
curl -X POST http://localhost:5000/api/v1/barrels/1/review \
  -H "Content-Type: application/json" \
  -d '{
    "operator_role": "ENV_AUDITOR",
    "operator_name": "王复核",
    "notes": "标识清晰，包装完好"
  }'

# === 桶 B: HW12 类别，180.3kg ===
# 车间创建
curl -X POST http://localhost:5000/api/v1/barrels \
  -H "Content-Type: application/json" \
  -d '{
    "barrel_no": "B-BATCH-DEMO-B",
    "waste_category_id": 2,
    "operator_role": "WORKSHOP",
    "operator_name": "张工"
  }'

# 仓管称重入库（假设返回id=2）
curl -X POST http://localhost:5000/api/v1/barrels/2/weigh \
  -H "Content-Type: application/json" \
  -d '{
    "weight_kg": 180.3,
    "storage_location_id": 2,
    "tag_code": "TAG-BATCH-DEMO-B",
    "operator_role": "WAREHOUSE",
    "operator_name": "李仓管"
  }'

# 环保复核
curl -X POST http://localhost:5000/api/v1/barrels/2/review \
  -H "Content-Type: application/json" \
  -d '{
    "operator_role": "ENV_AUDITOR",
    "operator_name": "王复核",
    "notes": "标识清晰，包装完好"
  }'
```

### 步骤1: 运输员创建转运批次（合批）

> 批次总重量自动计算 = 250.5 + 180.3 = **430.8kg**

```bash
curl -X POST http://localhost:5000/api/v1/batches \
  -H "Content-Type: application/json" \
  -d '{
    "batch_no": "BATCH-DEMO-001",
    "vehicle_no": "京A-DEMO01",
    "driver_name": "赵司机",
    "driver_phone": "13800138000",
    "expected_exit_time": "2026-06-15T18:00:00",
    "manifest_no": "HB-LD-DEMO-001",
    "barrel_ids": [1, 2],
    "operator_role": "TRANSPORT",
    "operator_name": "赵司机"
  }'
```

**响应说明**：返回批次详情，`total_weight_kg` 应为 430.8，批次内两个桶的状态均变为 `BATCHED`，此时 **库位容量不释放**（桶仍在库位，等待装车）。

### 步骤2: 查询批次详情（验证桶清单）

```bash
# 假设返回批次 id=1
curl http://localhost:5000/api/v1/batches/1
```

**响应**：包含 `barrel_count=2`，`barrels` 数组包含两个桶，总重量 430.8kg。

### 步骤3: 装车（沿用现有装车流程，批次自动完成）

```bash
# 桶 1 装车，联单号必须与批次一致
curl -X POST http://localhost:5000/api/v1/barrels/1/load \
  -H "Content-Type: application/json" \
  -d '{
    "manifest_no": "HB-LD-DEMO-001",
    "operator_role": "TRANSPORT",
    "operator_name": "赵司机"
  }'

# 桶 2 装车
curl -X POST http://localhost:5000/api/v1/barrels/2/load \
  -H "Content-Type: application/json" \
  -d '{
    "manifest_no": "HB-LD-DEMO-001",
    "operator_role": "TRANSPORT",
    "operator_name": "赵司机"
  }'
```

**效果**：
- 桶状态变为 `LOADED`
- 库位 STORE-B 容量释放（减少 430.8kg）
- 批次状态自动变为 `COMPLETED`（所有桶都装车后）

### 步骤4: 查询库位容量（验证释放）

```bash
curl http://localhost:5000/api/v1/locations
```

**验证**：STORE-B 的 `current_usage_kg` 应减少 430.8kg。

### 步骤5: 审计追踪（验证批次关联）

```bash
# 查看桶 A 的审计历史
curl http://localhost:5000/api/v1/barrels/1/audit
```

**验证**：`status_history` 中 BATCHED 和 LOADED 两条记录都带有 `transport_batch_id`，可追溯属于哪个批次。

---

## 转运批次: 取消流程 curl 样例

### 前置: 创建一个待取消的批次

```bash
# 准备两个已复核桶（id=3, 4），过程略...

# 创建批次
curl -X POST http://localhost:5000/api/v1/batches \
  -H "Content-Type: application/json" \
  -d '{
    "batch_no": "BATCH-CANCEL-DEMO",
    "vehicle_no": "京A-CANCEL",
    "driver_name": "钱司机",
    "expected_exit_time": "2026-06-15T19:00:00",
    "manifest_no": "HB-CANCEL-DEMO",
    "barrel_ids": [3, 4],
    "operator_role": "TRANSPORT",
    "operator_name": "钱司机"
  }'
```

### 取消批次（环保复核员或运输员角色）

```bash
# 假设批次 id=2，使用环保复核员角色取消
curl -X POST http://localhost:5000/api/v1/batches/2/cancel \
  -H "Content-Type: application/json" \
  -d '{
    "cancel_reason": "车辆临时故障，改期运输",
    "operator_role": "ENV_AUDITOR",
    "operator_name": "王复核"
  }'
```

**取消效果**：
1. 批次状态变为 `CANCELLED`，记录取消原因、取消人、取消时间
2. 桶 3 和桶 4 的状态恢复为 `REVIEWED`
3. 桶 3 和桶 4 的 `transport_batch_id` 清空（可重新合批）
4. 库位容量 **不变**（取消批次不影响库位）
5. 每个桶的状态历史中写入一条记录：`BATCHED → REVIEWED`，备注包含取消原因

---

## 转运批次: 非法路径测试（curl 样例，预期失败）

### 1. 包含未复核桶(CREATED)的合批

```bash
curl -X POST http://localhost:5000/api/v1/batches \
  -H "Content-Type: application/json" \
  -d '{
    "batch_no": "BATCH-ERR-1",
    "vehicle_no": "京A-ERR1",
    "driver_name": "测试",
    "expected_exit_time": "2026-06-15T20:00:00",
    "manifest_no": "HB-ERR-1",
    "barrel_ids": [1, 999],
    "operator_role": "TRANSPORT",
    "operator_name": "测试"
  }'
```

**预期错误**：`不符合合批条件，只有已复核(REVIEWED)状态的桶才能合批`

### 2. 同一桶同时进入两个未完成批次

```bash
# 先让桶成功加入一个批次（假设桶 id=5 状态为 REVIEWED）
curl -X POST http://localhost:5000/api/v1/batches ... # 包含 [5]

# 再尝试让它加入另一个批次
curl -X POST http://localhost:5000/api/v1/batches \
  -H "Content-Type: application/json" \
  -d '{
    "batch_no": "BATCH-ERR-2",
    ...,
    "barrel_ids": [5, 6],
    ...
  }'
```

**预期错误**：`桶 xxx (状态: BATCHED) 不符合合批条件` 或 `已存在于未完成批次 xxx 中`

### 3. 仓管角色越权创建批次

```bash
curl -X POST http://localhost:5000/api/v1/batches \
  -H "Content-Type: application/json" \
  -d '{
    ...,
    "operator_role": "WAREHOUSE",
    "operator_name": "李仓管"
  }'
```

**预期错误**：`角色 WAREHOUSE 无权执行 BATCHED 操作`

### 4. 车间角色越权取消批次

```bash
curl -X POST http://localhost:5000/api/v1/batches/1/cancel \
  -H "Content-Type: application/json" \
  -d '{
    "cancel_reason": "测试越权",
    "operator_role": "WORKSHOP",
    "operator_name": "张工"
  }'
```

**预期错误**：`角色 WORKSHOP 无权执行批次取消操作`

---

## 转运批次: 查询与导出接口

```bash
# 查询所有批次
curl http://localhost:5000/api/v1/batches

# 按状态筛选
curl "http://localhost:5000/api/v1/batches?status=PENDING"
curl "http://localhost:5000/api/v1/batches?status=COMPLETED"
curl "http://localhost:5000/api/v1/batches?status=CANCELLED"

# 查询批次详情（含桶清单）
curl http://localhost:5000/api/v1/batches/1

# === 批次导出 ===
# JSON 格式
curl http://localhost:5000/api/v1/batches/export/json

# CSV 格式
curl http://localhost:5000/api/v1/batches/export/csv -o batches_export.csv

# === 审计导出（含批次信息）===
# JSON: 每个桶记录包含 transport_batch_id, transport_batch_no 字段
curl http://localhost:5000/api/v1/audit/export/json

# CSV: 增加"转运批次号"列，状态历史中标注[批次:ID]
curl http://localhost:5000/api/v1/audit/export/csv -o audit_with_batches.csv
```

---

## 撤销操作

```bash
curl -X POST http://localhost:5000/api/v1/barrels/1/cancel \
  -H "Content-Type: application/json" \
  -d '{
    "cancel_reason": "标签损坏，需重新贴标",
    "operator_role": "WAREHOUSE",
    "operator_name": "李仓管"
  }'
```

---

## 非法路径测试（curl 样例）

### 1. 负重量校验

```bash
curl -X POST http://localhost:5000/api/v1/barrels/1/weigh \
  -H "Content-Type: application/json" \
  -d '{
    "weight_kg": -10,
    "storage_location_id": 1,
    "tag_code": "TAG-TEST-001",
    "operator_role": "WAREHOUSE",
    "operator_name": "李仓管"
  }'
```

**预期错误**：`重量必须大于0`

### 2. 仓管越权装车

```bash
curl -X POST http://localhost:5000/api/v1/barrels/1/load \
  -H "Content-Type: application/json" \
  -d '{
    "manifest_no": "HB-TEST-001",
    "operator_role": "WAREHOUSE",
    "operator_name": "李仓管"
  }'
```

**预期错误**：`角色 WAREHOUSE 无权执行 LOADED 操作`

### 3. 重复标签码

先创建并称重第一个桶：
```bash
# 创建第二个桶
curl -X POST http://localhost:5000/api/v1/barrels \
  -H "Content-Type: application/json" \
  -d '{
    "barrel_no": "B-2024-0002",
    "waste_category_id": 1,
    "operator_role": "WORKSHOP",
    "operator_name": "张工"
  }'

# 尝试使用重复标签码
curl -X POST http://localhost:5000/api/v1/barrels/2/weigh \
  -H "Content-Type: application/json" \
  -d '{
    "weight_kg": 100,
    "storage_location_id": 1,
    "tag_code": "TAG-HW08-0001",
    "operator_role": "WAREHOUSE",
    "operator_name": "李仓管"
  }'
```

**预期错误**：`标签码 TAG-HW08-0001 已被使用`

### 4. 库位容量超限

先填满 STORE-A 库位（容量5000kg）：
```bash
# 创建多个桶，总重量超过5000kg
for i in {3..22}; do
  curl -X POST http://localhost:5000/api/v1/barrels \
    -H "Content-Type: application/json" \
    -d "{\"barrel_no\":\"B-2024-$(printf %04d $i)\",\"waste_category_id\":1,\"operator_role\":\"WORKSHOP\",\"operator_name\":\"张工\"}"
done

# 逐个称重入库，每个260kg，20个就是5200kg，超过5000
for i in {3..22}; do
  echo "=== 处理桶 $i ==="
  curl -X POST http://localhost:5000/api/v1/barrels/$i/weigh \
    -H "Content-Type: application/json" \
    -d "{\"weight_kg\":260,\"storage_location_id\":1,\"tag_code\":\"TAG-OVER-$i\",\"operator_role\":\"WAREHOUSE\",\"operator_name\":\"李仓管\"}"
  echo ""
done
```

**预期**：第20个桶（5200kg > 5000kg）时返回错误：
`库位 STORE-A 容量不足: 剩余 Xkg, 需要 260kg`

### 5. 跨类别存储（类别筛选校验）

HW08 类别桶尝试存入 STORE-B（仅允许 HW12）：
```bash
curl -X POST http://localhost:5000/api/v1/barrels/2/weigh \
  -H "Content-Type: application/json" \
  -d '{
    "weight_kg": 100,
    "storage_location_id": 2,
    "tag_code": "TAG-WRONG-CAT-001",
    "operator_role": "WAREHOUSE",
    "operator_name": "李仓管"
  }'
```

**预期错误**：`库位 STORE-B 不允许存放该类危废`

### 6. 状态流转非法（跳过称重直接复核）

```bash
curl -X POST http://localhost:5000/api/v1/barrels/3/review \
  -H "Content-Type: application/json" \
  -d '{
    "operator_role": "ENV_AUDITOR",
    "operator_name": "王复核"
  }'
```

**预期错误**：`状态流转非法: 无法从 CREATED 转移到 REVIEWED`

---

## 查询接口

```bash
# 查询所有桶
curl http://localhost:5000/api/v1/barrels

# 按状态筛选
curl "http://localhost:5000/api/v1/barrels?status=WEIGHED"

# 按危废类别筛选
curl "http://localhost:5000/api/v1/barrels?category_code=HW08"

# 按库位筛选
curl "http://localhost:5000/api/v1/barrels?location_code=STORE-A"

# 查看单个桶详情
curl http://localhost:5000/api/v1/barrels/1

# 查看单个桶审计历史
curl http://localhost:5000/api/v1/barrels/1/audit
```

---

## 数据一致性保证

1. **原子性操作**：所有状态变更使用数据库事务，失败自动回滚
2. **操作失败不破坏原记录**：所有校验在事务提交前完成，失败时原记录保持不变
3. **完整状态历史**：每次状态变更都记录 `status_history` 表，包含：
   - 原状态、目标状态
   - 操作角色、操作人
   - 操作时间、备注
   - 重量、联单号等关键数据
4. **服务重启数据一致**：
   - 称重历史保存在 `status_history` 表
   - 复核人信息随状态历史永久保存
   - 撤销原因记录在桶主表和历史表
   - JSON/CSV 导出基于数据库实时查询，重启前后结果一致

---

## 完整测试脚本

```bash
# 运行完整测试（Windows PowerShell）
# 1. 启动服务
# 2. 另开终端执行：
python test_api.py
```

---

## 已取消批次追溯问题验证

### 问题描述
批次一旦取消，批次详情和 JSON/CSV 导出会把原来的桶数量、桶清单清空，导致无法对账和追溯。

### 根因
取消批次时执行 `barrel.transport_batch_id = None` 清空外键，查询端通过 `batch.barrels` 外键关联实时取桶 → 取消后读为空。

### 修复方案（最小改动）
新增 `resolve_batch_barrels(batch)` 查询层函数：
- 非 CANCELLED 状态：走原外键关联 `batch.barrels`
- CANCELLED 状态：从 `status_history` 表中 `transport_batch_id = batch.id AND to_status = 'BATCHED'` 的记录追溯原始成员

### 验证脚本

`test_batch_cancel_robust.py` 是环境自洽的三阶段测试脚本，自动准备数据、避开冲突，不依赖会话残留。

```bash
# ========== 三阶段完整验证 ==========
# 前置：启动服务
python run.py

# 阶段1：复现模式（临时注释修复代码时用，验证bug存在）
# 预期：CANCELLED 后 barrel_count=0，桶ID=[]
python test_batch_cancel_robust.py repro

# 阶段2：修复验证模式（代码已修复时用）
# 预期：CANCELLED 后仍保留完整数据，43项检查通过，自动保存快照
python test_batch_cancel_robust.py verify

# 阶段3：重启后一致性验证（重启服务后执行）
# 预期：重启前后逐字段/逐字符一致，42项检查通过
python test_batch_cancel_robust.py restart

# ========== 预期结果 ==========
# verify 模式：43/43 通过
#   取消前(PENDING):   20/20
#   取消后(CANCELLED): 23/23
#   重新合批:          0/0  (verify 模式跳过，保持桶状态稳定)
#
# restart 模式：42/42 通过
#   重启后独立验证: 19/19
#   重启前后对比:   23/23
```

### 验证内容（逐项核对用户可见字段）

| 接口 | 字段 | 取消前(PENDING) | 取消后(CANCELLED) | 重启后 |
|------|------|----------------|------------------|--------|
| 详情 GET /batches/{id} | barrel_count | 2 | 2 | 2 |
| 详情 | barrels.id 列表 | [9,10] | [9,10] | [9,10] |
| 详情 | barrels.barrel_no 列表 | [A,B] | [A,B] | [A,B] |
| 详情 | status | PENDING | CANCELLED | CANCELLED |
| 详情 | cancel_reason | None | 正确值 | 正确值 |
| 详情 | total_weight_kg | 390.5 | 390.5 | 390.5 |
| 列表 GET /batches | barrel_count | 2 | 2 | 2 |
| JSON导出 /batches/export/json | barrel_count | 2 | 2 | 2 |
| JSON导出 | barrels.id 列表 | [9,10] | [9,10] | [9,10] |
| JSON导出 | barrels.barrel_no 列表 | [A,B] | [A,B] | [A,B] |
| JSON导出 | status | PENDING | CANCELLED | CANCELLED |
| JSON导出 | cancel_reason | None | 正确值 | 正确值 |
| JSON导出 | total_weight_kg | 390.5 | 390.5 | 390.5 |
| CSV导出 /batches/export/csv | 桶数量列(col8) | 2 | 2 | 2 |
| CSV导出 | 状态列(col10) | PENDING | CANCELLED | CANCELLED |
| CSV导出 | 取消原因列(col11) | 空 | 正确值 | 正确值 |
| CSV导出 | 包含桶号 | ✓ | ✓ | ✓ |
| 桶 GET /barrels/{id} | status | BATCHED | REVIEWED | REVIEWED |
| 桶 | transport_batch_id | 非空 | None | None |
| 其他 | 取消后可重新合批 | - | ✓ | - |

