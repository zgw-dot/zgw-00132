from datetime import datetime
from .models import db, HazardousWasteBarrel, StatusHistory, WasteCategory, StorageLocation, TransportBatch, BARREL_STATUS, ROLES, BATCH_STATUS

STATUS_TRANSITIONS = {
    'CREATED': ['WEIGHED', 'CANCELLED'],
    'WEIGHED': ['REVIEWED', 'CANCELLED'],
    'REVIEWED': ['BATCHED', 'LOADED', 'CANCELLED'],
    'BATCHED': ['LOADED', 'REVIEWED'],
    'LOADED': [],
    'CANCELLED': []
}

ROLE_PERMISSIONS = {
    'WORKSHOP': ['CREATED'],
    'WAREHOUSE': ['WEIGHED'],
    'ENV_AUDITOR': ['REVIEWED'],
    'TRANSPORT': ['LOADED', 'BATCHED'],
}

ALLOW_CANCEL_ROLES = ['WAREHOUSE', 'ENV_AUDITOR']
ALLOW_CANCEL_BATCH_ROLES = ['ENV_AUDITOR', 'TRANSPORT']


class BusinessError(Exception):
    def __init__(self, message, code=400):
        self.message = message
        self.code = code
        super().__init__(message)


def _add_status_history(barrel, to_status, operator_role, operator_name,
                        weight_kg=None, manifest_no=None, transport_batch_id=None, notes=None):
    history = StatusHistory(
        barrel_id=barrel.id,
        from_status=barrel.status,
        to_status=to_status,
        operator_role=operator_role,
        operator_name=operator_name,
        weight_kg=weight_kg,
        manifest_no=manifest_no,
        transport_batch_id=transport_batch_id,
        notes=notes,
        timestamp=datetime.utcnow()
    )
    db.session.add(history)


def validate_category_exists(category_id):
    category = WasteCategory.query.filter_by(id=category_id, is_active=True).first()
    if not category:
        raise BusinessError(f"危废类别 ID {category_id} 不存在或已停用")
    return category


def validate_location_exists(location_id):
    location = StorageLocation.query.filter_by(id=location_id, is_active=True).first()
    if not location:
        raise BusinessError(f"库位 ID {location_id} 不存在或已停用")
    return location


def validate_barrel_exists(barrel_id):
    barrel = HazardousWasteBarrel.query.filter_by(id=barrel_id).first()
    if not barrel:
        raise BusinessError(f"危废桶 ID {barrel_id} 不存在", code=404)
    return barrel


def validate_status_transition(current_status, target_status):
    if target_status not in STATUS_TRANSITIONS.get(current_status, []):
        raise BusinessError(
            f"状态流转非法: 无法从 {current_status} 转移到 {target_status}"
        )


def validate_role_permission(role, target_status):
    if target_status == 'CANCELLED':
        if role not in ALLOW_CANCEL_ROLES:
            raise BusinessError(f"角色 {role} 无权执行撤销操作")
    else:
        allowed_statuses = ROLE_PERMISSIONS.get(role, [])
        if target_status not in allowed_statuses:
            raise BusinessError(
                f"角色 {role} 无权执行 {target_status} 操作"
            )


def validate_unique_tag_code(tag_code, exclude_barrel_id=None):
    query = HazardousWasteBarrel.query.filter_by(tag_code=tag_code)
    if exclude_barrel_id:
        query = query.filter(HazardousWasteBarrel.id != exclude_barrel_id)
    if query.first():
        raise BusinessError(f"标签码 {tag_code} 已被使用")


def validate_unique_barrel_no(barrel_no):
    if HazardousWasteBarrel.query.filter_by(barrel_no=barrel_no).first():
        raise BusinessError(f"桶号 {barrel_no} 已存在")


def validate_location_capacity(location, weight_kg, category_id):
    if category_id not in location.allowed_categories:
        raise BusinessError(
            f"库位 {location.code} 不允许存放该类危废"
        )
    if weight_kg > location.available_capacity_kg:
        raise BusinessError(
            f"库位 {location.code} 容量不足: "
            f"剩余 {location.available_capacity_kg}kg, 需要 {weight_kg}kg"
        )


def validate_batch_exists(batch_id):
    batch = TransportBatch.query.filter_by(id=batch_id).first()
    if not batch:
        raise BusinessError(f"转运批次 ID {batch_id} 不存在", code=404)
    return batch


def validate_unique_batch_no(batch_no):
    if TransportBatch.query.filter_by(batch_no=batch_no).first():
        raise BusinessError(f"批次号 {batch_no} 已存在")


def validate_batch_cancel_permission(role):
    if role not in ALLOW_CANCEL_BATCH_ROLES:
        raise BusinessError(f"角色 {role} 无权执行批次取消操作")


def validate_barrels_for_batching(barrel_ids):
    if not barrel_ids:
        raise BusinessError("至少需要选择一个危废桶")
    if len(barrel_ids) != len(set(barrel_ids)):
        raise BusinessError("桶列表中存在重复的桶ID")

    barrels = []
    for bid in barrel_ids:
        barrel = validate_barrel_exists(bid)
        barrels.append(barrel)

        if barrel.status != 'REVIEWED':
            raise BusinessError(
                f"桶 {barrel.barrel_no} (状态: {barrel.status}) 不符合合批条件，"
                f"只有已复核(REVIEWED)状态的桶才能合批"
            )

        existing_batch = TransportBatch.query.filter(
            TransportBatch.barrels.any(id=barrel.id),
            TransportBatch.status == 'PENDING'
        ).first()
        if existing_batch:
            raise BusinessError(
                f"桶 {barrel.barrel_no} 已存在于未完成批次 "
                f"{existing_batch.batch_no} 中，不能重复合批"
            )

    return barrels


def create_barrel(data):
    barrel_no = data['barrel_no']
    category_id = data['waste_category_id']
    operator_role = data['operator_role']
    operator_name = data['operator_name']

    validate_role_permission(operator_role, 'CREATED')
    validate_unique_barrel_no(barrel_no)
    category = validate_category_exists(category_id)

    barrel = HazardousWasteBarrel(
        barrel_no=barrel_no,
        waste_category_id=category.id,
        waste_category_code=category.code,
        status='CREATED'
    )
    db.session.add(barrel)
    db.session.flush()

    _add_status_history(
        barrel=barrel,
        to_status='CREATED',
        operator_role=operator_role,
        operator_name=operator_name,
        notes='创建危废桶登记'
    )

    db.session.commit()
    return barrel


def weigh_barrel(barrel_id, data):
    weight_kg = data['weight_kg']
    location_id = data['storage_location_id']
    tag_code = data['tag_code']
    operator_role = data['operator_role']
    operator_name = data['operator_name']

    if weight_kg <= 0:
        raise BusinessError("重量必须大于0")

    validate_role_permission(operator_role, 'WEIGHED')

    barrel = validate_barrel_exists(barrel_id)
    validate_status_transition(barrel.status, 'WEIGHED')
    validate_unique_tag_code(tag_code, exclude_barrel_id=barrel_id)

    location = validate_location_exists(location_id)
    validate_location_capacity(location, weight_kg, barrel.waste_category_id)

    old_location_id = barrel.storage_location_id
    old_weight = barrel.weight_kg or 0

    barrel.weight_kg = weight_kg
    barrel.storage_location_id = location.id
    barrel.storage_location_code = location.code
    barrel.tag_code = tag_code
    barrel.status = 'WEIGHED'

    if old_location_id and old_location_id != location_id:
        old_location = StorageLocation.query.get(old_location_id)
        if old_location:
            old_location.current_usage_kg -= old_weight

    location.current_usage_kg += weight_kg

    _add_status_history(
        barrel=barrel,
        to_status='WEIGHED',
        operator_role=operator_role,
        operator_name=operator_name,
        weight_kg=weight_kg,
        notes=f'入库称重完成，库位: {location.code}'
    )

    db.session.commit()
    return barrel


def review_barrel(barrel_id, data):
    operator_role = data['operator_role']
    operator_name = data['operator_name']
    notes = data.get('notes')

    validate_role_permission(operator_role, 'REVIEWED')

    barrel = validate_barrel_exists(barrel_id)
    validate_status_transition(barrel.status, 'REVIEWED')

    if barrel.weight_kg is None or barrel.tag_code is None:
        raise BusinessError("危废桶尚未完成称重入库，无法复核")

    barrel.status = 'REVIEWED'

    _add_status_history(
        barrel=barrel,
        to_status='REVIEWED',
        operator_role=operator_role,
        operator_name=operator_name,
        notes=notes or '环保复核通过'
    )

    db.session.commit()
    return barrel


def load_barrel(barrel_id, data):
    manifest_no = data['manifest_no']
    operator_role = data['operator_role']
    operator_name = data['operator_name']

    validate_role_permission(operator_role, 'LOADED')

    barrel = validate_barrel_exists(barrel_id)
    validate_status_transition(barrel.status, 'LOADED')

    batch_id = barrel.transport_batch_id
    if batch_id:
        batch = TransportBatch.query.get(batch_id)
        if batch and batch.status != 'PENDING':
            raise BusinessError(
                f"桶所属批次 {batch.batch_no} 状态为 {batch.status}，无法装车"
            )
        if batch and batch.manifest_no != manifest_no:
            raise BusinessError(
                f"桶所属批次联单号为 {batch.manifest_no}，与传入的 {manifest_no} 不一致"
            )

    barrel.manifest_no = manifest_no
    barrel.status = 'LOADED'

    if barrel.storage_location_id and barrel.weight_kg:
        location = StorageLocation.query.get(barrel.storage_location_id)
        if location:
            location.current_usage_kg -= barrel.weight_kg

    _add_status_history(
        barrel=barrel,
        to_status='LOADED',
        operator_role=operator_role,
        operator_name=operator_name,
        manifest_no=manifest_no,
        transport_batch_id=batch_id,
        notes=f'装车转移完成，联单号: {manifest_no}'
    )

    if batch_id:
        batch = TransportBatch.query.get(batch_id)
        if batch:
            all_loaded = all(b.status == 'LOADED' for b in batch.barrels)
            if all_loaded:
                batch.status = 'COMPLETED'
                batch.completed_at = datetime.utcnow()

    db.session.commit()
    return barrel


def cancel_barrel(barrel_id, data):
    cancel_reason = data['cancel_reason']
    operator_role = data['operator_role']
    operator_name = data['operator_name']

    validate_role_permission(operator_role, 'CANCELLED')

    barrel = validate_barrel_exists(barrel_id)

    if barrel.status in ['LOADED', 'CANCELLED', 'BATCHED']:
        if barrel.status == 'BATCHED':
            raise BusinessError(f"桶 {barrel.barrel_no} 已加入转运批次，不能单独撤销，请先取消批次")
        raise BusinessError(f"当前状态 {barrel.status} 不允许撤销")

    old_status = barrel.status
    old_location_usage = 0
    location = None

    if barrel.storage_location_id and barrel.weight_kg:
        location = StorageLocation.query.get(barrel.storage_location_id)
        if location:
            old_location_usage = barrel.weight_kg
            location.current_usage_kg -= old_location_usage

    barrel.status = 'CANCELLED'
    barrel.cancel_reason = cancel_reason

    _add_status_history(
        barrel=barrel,
        to_status='CANCELLED',
        operator_role=operator_role,
        operator_name=operator_name,
        notes=f'撤销原因: {cancel_reason}'
    )

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        if location and old_location_usage > 0:
            location.current_usage_kg += old_location_usage
        raise BusinessError(f"撤销操作失败: {str(e)}")

    return barrel


def get_barrel(barrel_id):
    return validate_barrel_exists(barrel_id)


def list_barrels(status=None, category_code=None, location_code=None):
    query = HazardousWasteBarrel.query

    if status:
        if status not in BARREL_STATUS:
            raise BusinessError(f"无效的状态值: {status}")
        query = query.filter_by(status=status)

    if category_code:
        query = query.filter_by(waste_category_code=category_code)

    if location_code:
        query = query.filter_by(storage_location_code=location_code)

    return query.order_by(HazardousWasteBarrel.created_at.desc()).all()


def list_categories():
    return WasteCategory.query.filter_by(is_active=True).all()


def list_locations():
    return StorageLocation.query.filter_by(is_active=True).all()


def get_barrel_audit(barrel_id):
    barrel = validate_barrel_exists(barrel_id)
    return {
        'barrel': barrel,
        'status_history': barrel.status_history
    }


def export_all_audit():
    barrels = HazardousWasteBarrel.query.order_by(HazardousWasteBarrel.created_at.desc()).all()
    result = []
    for barrel in barrels:
        barrel_data = {
            'id': barrel.id,
            'barrel_no': barrel.barrel_no,
            'waste_category_code': barrel.waste_category_code,
            'weight_kg': barrel.weight_kg,
            'storage_location_code': barrel.storage_location_code,
            'tag_code': barrel.tag_code,
            'manifest_no': barrel.manifest_no,
            'transport_batch_id': barrel.transport_batch_id,
            'transport_batch_no': barrel.transport_batch.batch_no if barrel.transport_batch else None,
            'status': barrel.status,
            'cancel_reason': barrel.cancel_reason,
            'created_at': barrel.created_at.isoformat() if barrel.created_at else None,
            'updated_at': barrel.updated_at.isoformat() if barrel.updated_at else None,
            'status_history': [
                {
                    'from_status': h.from_status,
                    'to_status': h.to_status,
                    'operator_role': h.operator_role,
                    'operator_name': h.operator_name,
                    'weight_kg': h.weight_kg,
                    'manifest_no': h.manifest_no,
                    'transport_batch_id': h.transport_batch_id,
                    'notes': h.notes,
                    'timestamp': h.timestamp.isoformat() if h.timestamp else None
                }
                for h in barrel.status_history
            ]
        }
        result.append(barrel_data)
    return result


def create_transport_batch(data):
    batch_no = data['batch_no']
    vehicle_no = data['vehicle_no']
    driver_name = data['driver_name']
    driver_phone = data.get('driver_phone')
    expected_exit_time = data['expected_exit_time']
    manifest_no = data['manifest_no']
    barrel_ids = data['barrel_ids']
    operator_role = data['operator_role']
    operator_name = data['operator_name']

    validate_role_permission(operator_role, 'BATCHED')
    validate_unique_batch_no(batch_no)

    barrels = validate_barrels_for_batching(barrel_ids)

    total_weight = sum(b.weight_kg or 0 for b in barrels)

    batch = TransportBatch(
        batch_no=batch_no,
        vehicle_no=vehicle_no,
        driver_name=driver_name,
        driver_phone=driver_phone,
        expected_exit_time=expected_exit_time,
        manifest_no=manifest_no,
        total_weight_kg=total_weight,
        status='PENDING',
        created_by_role=operator_role,
        created_by_name=operator_name
    )
    db.session.add(batch)
    db.session.flush()

    for barrel in barrels:
        barrel.transport_batch_id = batch.id
        barrel.status = 'BATCHED'
        _add_status_history(
            barrel=barrel,
            to_status='BATCHED',
            operator_role=operator_role,
            operator_name=operator_name,
            transport_batch_id=batch.id,
            notes=f'加入转运批次: {batch_no}'
        )

    db.session.commit()
    return batch


def cancel_transport_batch(batch_id, data):
    cancel_reason = data['cancel_reason']
    operator_role = data['operator_role']
    operator_name = data['operator_name']

    validate_batch_cancel_permission(operator_role)

    batch = validate_batch_exists(batch_id)

    if batch.status == 'COMPLETED':
        raise BusinessError(f"批次 {batch.batch_no} 已完成装车，无法取消")
    if batch.status == 'CANCELLED':
        raise BusinessError(f"批次 {batch.batch_no} 已被取消，无需重复操作")

    barrels_to_restore = []
    for barrel in batch.barrels:
        if barrel.status == 'BATCHED':
            barrels_to_restore.append(barrel)
        elif barrel.status == 'LOADED':
            raise BusinessError(
                f"批次中桶 {barrel.barrel_no} 已完成装车，无法取消批次"
            )

    now = datetime.utcnow()
    batch.status = 'CANCELLED'
    batch.cancel_reason = cancel_reason
    batch.cancelled_by_role = operator_role
    batch.cancelled_by_name = operator_name
    batch.cancelled_at = now

    for barrel in barrels_to_restore:
        barrel.status = 'REVIEWED'
        barrel.transport_batch_id = None
        _add_status_history(
            barrel=barrel,
            to_status='REVIEWED',
            operator_role=operator_role,
            operator_name=operator_name,
            transport_batch_id=batch.id,
            notes=f'批次取消，恢复至已复核状态。取消原因: {cancel_reason}'
        )

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        raise BusinessError(f"取消批次操作失败: {str(e)}")

    return batch


def list_transport_batches(status=None):
    query = TransportBatch.query
    if status:
        if status not in BATCH_STATUS:
            raise BusinessError(f"无效的批次状态值: {status}")
        query = query.filter_by(status=status)
    return query.order_by(TransportBatch.created_at.desc()).all()


def resolve_batch_barrels(batch):
    if batch.status != 'CANCELLED':
        return list(batch.barrels)
    history_records = StatusHistory.query.filter_by(
        transport_batch_id=batch.id,
        to_status='BATCHED'
    ).distinct(StatusHistory.barrel_id).all()
    barrel_ids = [h.barrel_id for h in history_records]
    if not barrel_ids:
        return []
    barrels = HazardousWasteBarrel.query.filter(
        HazardousWasteBarrel.id.in_(barrel_ids)
    ).all()
    return sorted(barrels, key=lambda b: b.id)


def get_transport_batch(batch_id):
    return validate_batch_exists(batch_id)


def get_batch_with_details(batch_id):
    batch = validate_batch_exists(batch_id)
    barrels = resolve_batch_barrels(batch)
    return {
        'batch': batch,
        'barrels': barrels,
        'barrel_count': len(barrels)
    }


def export_all_batches():
    batches = TransportBatch.query.order_by(TransportBatch.created_at.desc()).all()
    result = []
    for batch in batches:
        barrels = resolve_batch_barrels(batch)
        barrel_details = []
        for b in barrels:
            barrel_details.append({
                'barrel_id': b.id,
                'barrel_no': b.barrel_no,
                'waste_category_code': b.waste_category_code,
                'weight_kg': b.weight_kg,
                'storage_location_code': b.storage_location_code,
                'tag_code': b.tag_code,
                'status': b.status
            })
        batch_data = {
            'id': batch.id,
            'batch_no': batch.batch_no,
            'vehicle_no': batch.vehicle_no,
            'driver_name': batch.driver_name,
            'driver_phone': batch.driver_phone,
            'expected_exit_time': batch.expected_exit_time.isoformat() if batch.expected_exit_time else None,
            'manifest_no': batch.manifest_no,
            'total_weight_kg': batch.total_weight_kg,
            'barrel_count': len(barrels),
            'barrels': barrel_details,
            'status': batch.status,
            'cancel_reason': batch.cancel_reason,
            'cancelled_by_role': batch.cancelled_by_role,
            'cancelled_by_name': batch.cancelled_by_name,
            'cancelled_at': batch.cancelled_at.isoformat() if batch.cancelled_at else None,
            'created_by_role': batch.created_by_role,
            'created_by_name': batch.created_by_name,
            'created_at': batch.created_at.isoformat() if batch.created_at else None,
            'completed_at': batch.completed_at.isoformat() if batch.completed_at else None
        }
        result.append(batch_data)
    return result
