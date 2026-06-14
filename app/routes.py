import io
import csv
from datetime import datetime
from flask import Blueprint, request, jsonify, Response
from marshmallow import ValidationError

from . import services
from .services import BusinessError
from .schemas import (
    HazardousWasteBarrelSchema,
    StatusHistorySchema,
    WasteCategorySchema,
    StorageLocationSchema,
    CreateBarrelSchema,
    WeighBarrelSchema,
    ReviewBarrelSchema,
    LoadBarrelSchema,
    CancelBarrelSchema
)

api_bp = Blueprint('api', __name__, url_prefix='/api/v1')

barrel_schema = HazardousWasteBarrelSchema()
barrels_schema = HazardousWasteBarrelSchema(many=True)
category_schema = WasteCategorySchema(many=True)
location_schema = StorageLocationSchema(many=True)
history_schema = StatusHistorySchema(many=True)


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
        '当前状态', '撤销原因', '创建时间', '更新时间',
        '状态变更历史'
    ]
    writer.writerow(header)

    for record in data:
        history_parts = []
        for h in record['status_history']:
            history_parts.append(
                f"{h['from_status'] or '-'}→{h['to_status']} "
                f"({h['operator_role']}:{h['operator_name']}) "
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


@api_bp.route('/status', methods=['GET'])
def get_system_status():
    from .models import BARREL_STATUS, ROLES
    return jsonify({
        'barrel_statuses': BARREL_STATUS,
        'roles': ROLES,
        'status_transitions': services.STATUS_TRANSITIONS,
        'role_permissions': services.ROLE_PERMISSIONS
    })
