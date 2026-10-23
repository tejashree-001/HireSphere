import os
import click
from flask import Flask, jsonify, render_template
from flask_login import current_user
from sqlalchemy import text, select, func

from app.config import Config
from app.extensions import db, migrate, login_manager, csrf
from app.models import User, Notification
from app.public.routes import public_bp
from app.auth.routes import auth_bp


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)

    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please log in to continue."
    login_manager.login_message_category = "warning"

    @login_manager.user_loader
    def load_user(user_id):
        try:
            return db.session.get(User, int(user_id))
        except (ValueError, TypeError):
            return None

    app.register_blueprint(public_bp)
    app.register_blueprint(auth_bp)

    @app.context_processor
    def inject_notification_count():
        if not current_user.is_authenticated:
            return {"unread_notification_count": 0}
        try:
            count = db.session.scalar(select(func.count(Notification.id)).where(
                Notification.user_id == current_user.id,
                Notification.is_read.is_(False)
            )) or 0
            return {"unread_notification_count": count}
        except Exception:
            db.session.rollback()
            return {"unread_notification_count": 0}

    @app.cli.command("promote-admin")
    @click.argument("email")
    def promote_admin_command(email):
        """Promote an existing account to admin; never exposes admin registration publicly."""
        with app.app_context():
            account = db.session.scalar(select(User).where(User.email == email.strip().lower()))
            if account is None:
                raise click.ClickException("No account exists with that email. Register/login as a normal user first.")
            account.role = "admin"
            db.session.commit()
            click.echo(f"{account.email} is now an admin. Log out and log back in.")

    @app.get("/health")
    def health():
        return jsonify(status="ok", application="HireSphere")

    @app.get("/health/db")
    def database_health():
        try:
            db.session.execute(text("SELECT 1"))
            return jsonify(status="ok", database="connected")
        except Exception:
            app.logger.exception("Database health check failed")
            return jsonify(status="error", database="unavailable"), 503
        finally:
            db.session.remove()

    @app.cli.command("init-db")
    def init_db_command():
        """Create missing database tables; existing tables are not altered."""
        with app.app_context():
            db.create_all()
        print("HireSphere database tables are ready.")

    @app.errorhandler(404)
    def not_found(error):
        return render_template("errors/404.html"), 404

    @app.errorhandler(413)
    def file_too_large(error):
        from flask import flash, redirect, url_for, request
        flash("That upload is too large. Maximum file size is 5 MB.", "danger")
        if request.referrer:
            return redirect(request.referrer)
        return redirect(url_for("auth.dashboard"))

    @app.errorhandler(500)
    def server_error(error):
        db.session.rollback()
        return render_template("errors/500.html"), 500

    return app
