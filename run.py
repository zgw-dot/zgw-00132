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
            'version': '1.0.0',
            'endpoints': {
                'health': '/health',
                'api_root': '/api/v1',
                'categories': '/api/v1/categories',
                'locations': '/api/v1/locations',
                'barrels': '/api/v1/barrels',
                'system_status': '/api/v1/status',
                'export_json': '/api/v1/audit/export/json',
                'export_csv': '/api/v1/audit/export/csv'
            },
            'status_flow': 'CREATED → WEIGHED → REVIEWED → LOADED',
            'roles': {
                'WORKSHOP': '车间（创建）',
                'WAREHOUSE': '仓管（称重入库）',
                'ENV_AUDITOR': '环保复核员（复核）',
                'TRANSPORT': '运输员（装车转移）'
            }
        })

    return app


if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=5000, debug=False)
