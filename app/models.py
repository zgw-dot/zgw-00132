from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

BARREL_STATUS = [
    'CREATED',
    'WEIGHED',
    'REVIEWED',
    'BATCHED',
    'LOADED',
    'CANCELLED'
]

BATCH_STATUS = [
    'PENDING',
    'COMPLETED',
    'CANCELLED'
]

ROLES = [
    'WORKSHOP',
    'WAREHOUSE',
    'ENV_AUDITOR',
    'TRANSPORT'
]


class WasteCategory(db.Model):
    __tablename__ = 'waste_categories'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(500))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class StorageLocation(db.Model):
    __tablename__ = 'storage_locations'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    max_capacity_kg = db.Column(db.Float, nullable=False)
    allowed_category_ids = db.Column(db.String(200), nullable=False)
    current_usage_kg = db.Column(db.Float, default=0.0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def allowed_categories(self):
        if not self.allowed_category_ids:
            return []
        return [int(cid) for cid in self.allowed_category_ids.split(',') if cid.strip()]

    @allowed_categories.setter
    def allowed_categories(self, category_ids):
        self.allowed_category_ids = ','.join(str(cid) for cid in category_ids)

    @property
    def available_capacity_kg(self):
        return self.max_capacity_kg - self.current_usage_kg


class HazardousWasteBarrel(db.Model):
    __tablename__ = 'hazardous_waste_barrels'

    id = db.Column(db.Integer, primary_key=True)
    barrel_no = db.Column(db.String(50), unique=True, nullable=False)
    waste_category_id = db.Column(db.Integer, db.ForeignKey('waste_categories.id'), nullable=False)
    waste_category_code = db.Column(db.String(20), nullable=False)
    weight_kg = db.Column(db.Float)
    storage_location_id = db.Column(db.Integer, db.ForeignKey('storage_locations.id'))
    storage_location_code = db.Column(db.String(20))
    tag_code = db.Column(db.String(100), unique=True)
    manifest_no = db.Column(db.String(100))
    transport_batch_id = db.Column(db.Integer, db.ForeignKey('transport_batches.id'))
    status = db.Column(db.String(20), default='CREATED', nullable=False)
    cancel_reason = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    waste_category = db.relationship('WasteCategory', backref='barrels')
    storage_location = db.relationship('StorageLocation', backref='barrels')
    transport_batch = db.relationship('TransportBatch', backref='barrels')
    status_history = db.relationship('StatusHistory', backref='barrel', cascade='all, delete-orphan', order_by='StatusHistory.timestamp')


class StatusHistory(db.Model):
    __tablename__ = 'status_history'

    id = db.Column(db.Integer, primary_key=True)
    barrel_id = db.Column(db.Integer, db.ForeignKey('hazardous_waste_barrels.id'), nullable=False)
    from_status = db.Column(db.String(20))
    to_status = db.Column(db.String(20), nullable=False)
    operator_role = db.Column(db.String(20), nullable=False)
    operator_name = db.Column(db.String(100), nullable=False)
    weight_kg = db.Column(db.Float)
    manifest_no = db.Column(db.String(100))
    transport_batch_id = db.Column(db.Integer, db.ForeignKey('transport_batches.id'))
    notes = db.Column(db.String(500))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    transport_batch = db.relationship('TransportBatch', backref='status_histories')


class TransportBatch(db.Model):
    __tablename__ = 'transport_batches'

    id = db.Column(db.Integer, primary_key=True)
    batch_no = db.Column(db.String(50), unique=True, nullable=False)
    vehicle_no = db.Column(db.String(50), nullable=False)
    driver_name = db.Column(db.String(100), nullable=False)
    driver_phone = db.Column(db.String(20))
    expected_exit_time = db.Column(db.DateTime, nullable=False)
    manifest_no = db.Column(db.String(100), nullable=False)
    total_weight_kg = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(20), default='PENDING', nullable=False)
    cancel_reason = db.Column(db.String(500))
    cancelled_by_role = db.Column(db.String(20))
    cancelled_by_name = db.Column(db.String(100))
    cancelled_at = db.Column(db.DateTime)
    created_by_role = db.Column(db.String(20), nullable=False)
    created_by_name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = db.Column(db.DateTime)
