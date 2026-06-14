from marshmallow import Schema, fields, validate, validates, ValidationError
from .models import BARREL_STATUS, ROLES, BATCH_STATUS


class WasteCategorySchema(Schema):
    id = fields.Int(dump_only=True)
    code = fields.Str(required=True)
    name = fields.Str(required=True)
    description = fields.Str(allow_none=True)
    is_active = fields.Boolean()
    created_at = fields.DateTime(dump_only=True)


class StorageLocationSchema(Schema):
    id = fields.Int(dump_only=True)
    code = fields.Str(required=True)
    name = fields.Str(required=True)
    max_capacity_kg = fields.Float(required=True)
    allowed_category_ids = fields.Str(required=True)
    current_usage_kg = fields.Float(dump_only=True)
    available_capacity_kg = fields.Float(dump_only=True)
    is_active = fields.Boolean()
    created_at = fields.DateTime(dump_only=True)


class StatusHistorySchema(Schema):
    id = fields.Int(dump_only=True)
    barrel_id = fields.Int(required=True)
    from_status = fields.Str(allow_none=True)
    to_status = fields.Str(required=True, validate=validate.OneOf(BARREL_STATUS))
    operator_role = fields.Str(required=True, validate=validate.OneOf(ROLES))
    operator_name = fields.Str(required=True)
    weight_kg = fields.Float(allow_none=True)
    manifest_no = fields.Str(allow_none=True)
    transport_batch_id = fields.Int(allow_none=True, dump_only=True)
    notes = fields.Str(allow_none=True)
    timestamp = fields.DateTime(dump_only=True)


class HazardousWasteBarrelSchema(Schema):
    id = fields.Int(dump_only=True)
    barrel_no = fields.Str(required=True)
    waste_category_id = fields.Int(required=True)
    waste_category_code = fields.Str(dump_only=True)
    weight_kg = fields.Float(allow_none=True)
    storage_location_id = fields.Int(allow_none=True)
    storage_location_code = fields.Str(dump_only=True)
    tag_code = fields.Str(allow_none=True)
    manifest_no = fields.Str(allow_none=True)
    transport_batch_id = fields.Int(allow_none=True, dump_only=True)
    status = fields.Str(dump_only=True, validate=validate.OneOf(BARREL_STATUS))
    cancel_reason = fields.Str(allow_none=True, dump_only=True)
    status_history = fields.Nested(StatusHistorySchema, many=True, dump_only=True)
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)


class CreateBarrelSchema(Schema):
    barrel_no = fields.Str(required=True)
    waste_category_id = fields.Int(required=True)
    operator_role = fields.Str(required=True, validate=validate.OneOf(ROLES))
    operator_name = fields.Str(required=True)


class WeighBarrelSchema(Schema):
    weight_kg = fields.Float(required=True)
    storage_location_id = fields.Int(required=True)
    tag_code = fields.Str(required=True)
    operator_role = fields.Str(required=True, validate=validate.OneOf(ROLES))
    operator_name = fields.Str(required=True)

    @validates('weight_kg')
    def validate_weight(self, value):
        if value <= 0:
            raise ValidationError("重量必须大于0")
        return value


class ReviewBarrelSchema(Schema):
    operator_role = fields.Str(required=True, validate=validate.OneOf(ROLES))
    operator_name = fields.Str(required=True)
    notes = fields.Str(allow_none=True)


class LoadBarrelSchema(Schema):
    manifest_no = fields.Str(required=True)
    operator_role = fields.Str(required=True, validate=validate.OneOf(ROLES))
    operator_name = fields.Str(required=True)


class CancelBarrelSchema(Schema):
    cancel_reason = fields.Str(required=True)
    operator_role = fields.Str(required=True, validate=validate.OneOf(ROLES))
    operator_name = fields.Str(required=True)


class CreateTransportBatchSchema(Schema):
    batch_no = fields.Str(required=True)
    vehicle_no = fields.Str(required=True)
    driver_name = fields.Str(required=True)
    driver_phone = fields.Str(allow_none=True)
    expected_exit_time = fields.DateTime(required=True)
    manifest_no = fields.Str(required=True)
    barrel_ids = fields.List(fields.Int(), required=True, validate=validate.Length(min=1))
    operator_role = fields.Str(required=True, validate=validate.OneOf(ROLES))
    operator_name = fields.Str(required=True)


class CancelTransportBatchSchema(Schema):
    cancel_reason = fields.Str(required=True)
    operator_role = fields.Str(required=True, validate=validate.OneOf(ROLES))
    operator_name = fields.Str(required=True)


class TransportBatchSchema(Schema):
    id = fields.Int(dump_only=True)
    batch_no = fields.Str(dump_only=True)
    vehicle_no = fields.Str(dump_only=True)
    driver_name = fields.Str(dump_only=True)
    driver_phone = fields.Str(dump_only=True, allow_none=True)
    expected_exit_time = fields.DateTime(dump_only=True)
    manifest_no = fields.Str(dump_only=True)
    total_weight_kg = fields.Float(dump_only=True)
    status = fields.Str(dump_only=True, validate=validate.OneOf(BATCH_STATUS))
    cancel_reason = fields.Str(dump_only=True, allow_none=True)
    cancelled_by_role = fields.Str(dump_only=True, allow_none=True)
    cancelled_by_name = fields.Str(dump_only=True, allow_none=True)
    cancelled_at = fields.DateTime(dump_only=True, allow_none=True)
    created_by_role = fields.Str(dump_only=True)
    created_by_name = fields.Str(dump_only=True)
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)
    completed_at = fields.DateTime(dump_only=True, allow_none=True)
    barrel_count = fields.Int(dump_only=True)
    barrels = fields.Nested(HazardousWasteBarrelSchema, many=True, dump_only=True, exclude=('status_history',))
