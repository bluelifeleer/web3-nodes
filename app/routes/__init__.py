from app.routes.admin import bp as admin_api_bp
from app.routes.auth import bp as auth_api_bp
from app.routes.files import bp as files_api_bp
from app.routes.finance import bp as finance_api_bp
from app.routes.nodes import bp as node_api_bp
from app.routes.pages import bp as pages_bp
from app.routes.pcdn import bp as pcdn_api_bp


def register_blueprints(flask_app):
    if admin_api_bp.name not in flask_app.blueprints:
        flask_app.register_blueprint(admin_api_bp)
    if auth_api_bp.name not in flask_app.blueprints:
        flask_app.register_blueprint(auth_api_bp)
    if files_api_bp.name not in flask_app.blueprints:
        flask_app.register_blueprint(files_api_bp)
    if finance_api_bp.name not in flask_app.blueprints:
        flask_app.register_blueprint(finance_api_bp)
    if node_api_bp.name not in flask_app.blueprints:
        flask_app.register_blueprint(node_api_bp)
    if pcdn_api_bp.name not in flask_app.blueprints:
        flask_app.register_blueprint(pcdn_api_bp)
    if pages_bp.name not in flask_app.blueprints:
        flask_app.register_blueprint(pages_bp)
    return flask_app
