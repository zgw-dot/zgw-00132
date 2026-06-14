import io
import csv
from datetime import datetime
from flask import Blueprint, request, jsonify, Response
from marshmallow import ValidationError

from . import services
from .services import BusinessError, resolve_batch_barrels
from .schemas import (
    HazardousWasteBarrelSchema,
    StatusHistorySchema,
    WasteCategorySchema,
    StorageLocationSchema,
    CreateBarrelSchema,
    WeighBarrelSchema,
    ReviewBarrelSchema,
    LoadBarrelSchema,
    CancelBarrelSchema,
    CreateTransportBatchSchema,
    CancelTransportBatchSchema,
    TransportBatchSchema
)

api_bp = Blueprint('api', __name__, url_prefix='/api/v1')

barrel_schema = HazardousWasteBarrelSchema()
barrels_schema = HazardousWasteBarrelSchema(many=True)
category_schema = WasteCategorySchema(many=True)
location_schema = StorageLocationSchema(many=True)
history_schema = StatusHistorySchema(many=True)
batch_schema = TransportBatchSchema()
batches_schema = TransportBatchSchema(many=True, exclude=('barrels',))


def json_error(message, code=400):
    return jsonify({'error': message, 'code': code}), code


@api_bp.route('/categories', methods=['GET'])
def get_categories():
    categories = services.list_categories()
    return jsonify(category_schema.dump(categories))


@api_bp.route('/locations', methods=['GET'])
def get_locations():
    locations = services.list_locations()
    return jsonify(location_schema.dump(locations))


@api_bp.route('/barrels', methods=['POST'])
def create_barrel():
    try:
        data = CreateBarrelSchema().load(request.get_json())
    except ValidationError as err:
        return json_error(f"参数校验失败: {err.messages}")

    try:
        barrel = services.create_barrel(data)
        return jsonify(barrel_schema.dump(barrel)), 201
    except BusinessError as e:
        return json_error(e.message, e.code)


@api_bp.route('/barrels/<int:barrel_id>/weigh', methods=['POST'])
def weigh_barrel(barrel_id):
    try:
        data = WeighBarrelSchema().load(request.get_json())
    except ValidationError as err:
        return json_error(f"参数校验失败: {err.messages}")

    try:
        barrel = services.weigh_barrel(barrel_id, data)
        return jsonify(barrel_schema.dump(barrel))
    except BusinessError as e:
        return json_error(e.message, e.code)


@api_bp.route('/barrels/<int:barrel_id>/review', methods=['POST'])
def review_barrel(barrel_id):
    try:
        data = ReviewBarrelSchema().load(request.get_json())
    except ValidationError as err:
        return json_error(f"参数校验失败: {err.messages}")

    try:
        barrel = services.review_barrel(barrel_id, data)
        return jsonify(barrel_schema.dump(barrel))
    except BusinessError as e:
        return json_error(e.message, e.code)


@api_bp.route('/barrels/<int:barrel_id>/load', methods=['POST'])
def load_barrel(barrel_id):
    try:
        data = LoadBarrelSchema().load(request.get_json())
    except ValidationError as err:
        return json_error(f"参数校验失败: {err.messages}")

    try:
        barrel = services.load_barrel(barrel_id, data)
        return jsonify(barrel_schema.dump(barrel))
    except BusinessError as e:
        return json_error(e.message, e.code)


@api_bp.route('/barrels/<int:barrel_id>/cancel', methods=['POST'])
def cancel_barrel(barrel_id):
    try:
        data = CancelBarrelSchema().load(request.get_json())
    except ValidationError as err:
        return json_error(f"参数校验失败: {err.messages}")

    try:
        barrel = services.cancel_barrel(barrel_id, data)
        return jsonify(barrel_schema.dump(barrel))
    except BusinessError as e:
        return json_error(e.message, e.code)


@api_bp.route('/barrels', methods=['GET'])
def list_barrels():
    status = request.args.get('status')
    category_code = request.args.get('category_code')
    location_code = request.args.get('location_code')

    try:
        barrels = services.list_barrels(status, category_code, location_code)
        return jsonify(barrels_schema.dump(barrels))
    except BusinessError as e:
        return json_error(e.message, e.code)


@api_bp.route('/barrels/<int:barrel_id>', methods=['GET'])
def get_barrel(barrel_id):
    try:
        barrel = services.get_barrel(barrel_id)
        return jsonify(barrel_schema.dump(barrel))
    except BusinessError as e:
        return json_error(e.message, e.code)


@api_bp.route('/barrels/<int:barrel_id>/audit', methods=['GET'])
def get_barrel_audit(barrel_id):
    try:
        audit_data = services.get_barrel_audit(barrel_id)
        return jsonify({
            'barrel': barrel_schema.dump(audit_data['barrel']),
            'status_history': history_schema.dump(audit_data['status_history'])
        })
    except BusinessError as e:
        return json_error(e.message, e.code)


@api_bp.route('/audit/export/json', methods=['GET'])
def export_audit_json():
    data = services.export_all_audit()
    return jsonify({
        'exported_at': datetime.utcnow().isoformat(),
        'total_records': len(data),
        'records': data
    })


@api_bp.route('/audit/export/csv', methods=['GET'])
def export_audit_csv():
    data = services.export_all_audit()

    output = io.StringIO()
    writer = csv.writer(output)

    header = [
        '桶号', '危废类别', '重量(kg)', '库位', '标签码', '联单号',
        '转运批次号', '当前状态', '撤销原因', '创建时间', '更新时间',
        '状态变更历史'
    ]
    writer.writerow(header)

    for record in data:
        history_parts = []
        for h in record['status_history']:
            batch_tag = f"[批次:{h['transport_batch_id']}]" if h.get('transport_batch_id') else ''
            history_parts.append(
                f"{h['from_status'] or '-'}→{h['to_status']} "
                f"({h['operator_role']}:{h['operator_name']}){batch_tag} "
                f"[{h['timestamp']}]"
            )
        history_str = ' | '.join(history_parts)

        row = [
            record['barrel_no'],
            record['waste_category_code'],
            record['weight_kg'] or '',
            record['storage_location_code'] or '',
            record['tag_code'] or '',
            record['manifest_no'] or '',
            record.get('transport_batch_no') or '',
            record['status'],
            record['cancel_reason'] or '',
            record['created_at'] or '',
            record['updated_at'] or '',
            history_str
        ]
        writer.writerow(row)

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv; charset=utf-8-sig',
        headers={
            'Content-Disposition': f'attachment; filename=hazardous_waste_audit_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
        }
    )


@api_bp.route('/batches', methods=['POST'])
def create_batch():
    try:
        data = CreateTransportBatchSchema().load(request.get_json())
    except ValidationError as err:
        return json_error(f"参数校验失败: {err.messages}")

    try:
        batch = services.create_transport_batch(data)
        details = services.get_batch_with_details(batch.id)
        return jsonify(batch_schema.dump(details['batch'])), 201
    except BusinessError as e:
        return json_error(e.message, e.code)


@api_bp.route('/batches', methods=['GET'])
def list_batches():
    status = request.args.get('status')
    try:
        batches = services.list_transport_batches(status)
        result = []
        for b in batches:
            data = batch_schema.dump(b)
            data['barrel_count'] = len(resolve_batch_barrels(b))
            result.append(data)
        return jsonify(result)
    except BusinessError as e:
        return json_error(e.message, e.code)


@api_bp.route('/batches/<int:batch_id>', methods=['GET'])
def get_batch(batch_id):
    try:
        details = services.get_batch_with_details(batch_id)
        data = batch_schema.dump(details['batch'])
        data['barrel_count'] = details['barrel_count']
        data['barrels'] = barrels_schema.dump(details['barrels'])
        return jsonify(data)
    except BusinessError as e:
        return json_error(e.message, e.code)


@api_bp.route('/batches/<int:batch_id>/cancel', methods=['POST'])
def cancel_batch(batch_id):
    try:
        data = CancelTransportBatchSchema().load(request.get_json())
    except ValidationError as err:
        return json_error(f"参数校验失败: {err.messages}")

    try:
        batch = services.cancel_transport_batch(batch_id, data)
        details = services.get_batch_with_details(batch.id)
        data = batch_schema.dump(details['batch'])
        data['barrel_count'] = details['barrel_count']
        data['barrels'] = barrels_schema.dump(details['barrels'])
        return jsonify(data)
    except BusinessError as e:
        return json_error(e.message, e.code)


@api_bp.route('/batches/export/json', methods=['GET'])
def export_batches_json():
    data = services.export_all_batches()
    return jsonify({
        'exported_at': datetime.utcnow().isoformat(),
        'total_batches': len(data),
        'batches': data
    })


@api_bp.route('/batches/export/csv', methods=['GET'])
def export_batches_csv():
    data = services.export_all_batches()

    output = io.StringIO()
    writer = csv.writer(output)

    header = [
        '批次号', '车牌号', '司机姓名', '司机电话', '预计出厂时间',
        '联单号', '总重量(kg)', '桶数量', '桶清单(桶号)', '当前状态',
        '取消原因', '取消人角色', '取消人', '取消时间',
        '创建人角色', '创建人', '创建时间', '完成时间'
    ]
    writer.writerow(header)

    for batch in data:
        barrel_nos = '; '.join(b['barrel_no'] for b in batch['barrels'])
        row = [
            batch['batch_no'],
            batch['vehicle_no'],
            batch['driver_name'],
            batch['driver_phone'] or '',
            batch['expected_exit_time'] or '',
            batch['manifest_no'],
            batch['total_weight_kg'],
            batch['barrel_count'],
            barrel_nos,
            batch['status'],
            batch['cancel_reason'] or '',
            batch['cancelled_by_role'] or '',
            batch['cancelled_by_name'] or '',
            batch['cancelled_at'] or '',
            batch['created_by_role'],
            batch['created_by_name'],
            batch['created_at'] or '',
            batch['completed_at'] or ''
        ]
        writer.writerow(row)

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv; charset=utf-8-sig',
        headers={
            'Content-Disposition': f'attachment; filename=transport_batches_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
        }
    )


@api_bp.route('/status', methods=['GET'])
def get_system_status():
    from .models import BARREL_STATUS, ROLES, BATCH_STATUS
    return jsonify({
        'barrel_statuses': BARREL_STATUS,
        'batch_statuses': BATCH_STATUS,
        'roles': ROLES,
        'status_transitions': services.STATUS_TRANSITIONS,
        'role_permissions': services.ROLE_PERMISSIONS,
        'batch_cancel_roles': services.ALLOW_CANCEL_BATCH_ROLES
    })
