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
