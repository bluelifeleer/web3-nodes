from app.routes.pages import bp as pages_bp


def register_blueprints(flask_app):
    if pages_bp.name not in flask_app.blueprints:
        flask_app.register_blueprint(pages_bp)
    return flask_app
