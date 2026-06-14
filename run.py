from flask import Flask, jsonify
from app.config import Config
from app.models import db
from app.database import init_db
from app.routes import api_bp


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)

    with app.app_context():
        init_db()

    app.register_blueprint(api_bp)

    @app.route('/health', methods=['GET'])
    def health_check():
        return jsonify({'status': 'ok', 'service': 'hazardous-waste-api'})

    @app.route('/', methods=['GET'])
    def index():
        return jsonify({
            'name': '危废暂存转移 API',
            'version': '1.1.0',
            'features': ['危废桶全生命周期管理', '转运批次合批管理'],
            'endpoints': {
                'health': '/health',
                'api_root': '/api/v1',
                'categories': '/api/v1/categories',
                'locations': '/api/v1/locations',
                'barrels': '/api/v1/barrels',
                'batches': '/api/v1/batches',
                'system_status': '/api/v1/status',
                'audit_export_json': '/api/v1/audit/export/json',
                'audit_export_csv': '/api/v1/audit/export/csv',
                'batch_export_json': '/api/v1/batches/export/json',
                'batch_export_csv': '/api/v1/batches/export/csv'
            },
            'status_flow': 'CREATED → WEIGHED → REVIEWED → BATCHED → LOADED',
            'batch_status_flow': 'PENDING → COMPLETED (或 CANCELLED)',
            'roles': {
                'WORKSHOP': '车间（创建桶）',
                'WAREHOUSE': '仓管（称重入库、撤销桶）',
                'ENV_AUDITOR': '环保复核员（复核、撤销桶、取消批次）',
                'TRANSPORT': '运输员（创建批次、取消批次、装车）'
            }
        })

    return app


if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=5000, debug=False)
