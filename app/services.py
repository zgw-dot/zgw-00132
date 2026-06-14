from datetime import datetime
from .models import db, HazardousWasteBarrel, StatusHistory, WasteCategory, StorageLocation, BARREL_STATUS, ROLES

STATUS_TRANSITIONS = {
    'CREATED': ['WEIGHED', 'CANCELLED'],
    'WEIGHED': ['REVIEWED', 'CANCELLED'],
    'REVIEWED': ['LOADED', 'CANCELLED'],
    'LOADED': [],
    'CANCELLED': []
}

ROLE_PERMISSIONS = {
    'WORKSHOP': ['CREATED'],
    'WAREHOUSE': ['WEIGHED'],
    'ENV_AUDITOR': ['REVIEWED'],
    'TRANSPORT': ['LOADED'],
}

ALLOW_CANCEL_ROLES = ['WAREHOUSE', 'ENV_AUDITOR']


class BusinessError(Exception):
    def __init__(self, message, code=400):
        self.message = message
        self.code = code
        super().__init__(message)


def _add_status_history(barrel, to_status, operator_role, operator_name,
                        weight_kg=None, manifest_no=None, notes=None):
    history = StatusHistory(
        barrel_id=barrel.id,
        from_status=barrel.status,
        to_status=to_status,
        operator_role=operator_role,
        operator_name=operator_name,
        weight_kg=weight_kg,
        manifest_no=manifest_no,
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
        notes=f'装车转移完成，联单号: {manifest_no}'
    )

    db.session.commit()
    return barrel


def cancel_barrel(barrel_id, data):
    cancel_reason = data['cancel_reason']
    operator_role = data['operator_role']
    operator_name = data['operator_name']

    validate_role_permission(operator_role, 'CANCELLED')

    barrel = validate_barrel_exists(barrel_id)

    if barrel.status in ['LOADED', 'CANCELLED']:
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
                    'notes': h.notes,
                    'timestamp': h.timestamp.isoformat() if h.timestamp else None
                }
                for h in barrel.status_history
            ]
        }
        result.append(barrel_data)
    return result
