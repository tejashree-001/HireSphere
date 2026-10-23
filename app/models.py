from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from app.extensions import db


def current_utc_time():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="candidate")
    # Backwards-compatible pointer to the candidate's current primary resume.
    resume_filename = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=current_utc_time)

    jobs = db.relationship(
        "Job", back_populates="employer", cascade="all, delete-orphan",
        foreign_keys="Job.employer_id"
    )
    applications = db.relationship(
        "Application", back_populates="candidate", cascade="all, delete-orphan",
        foreign_keys="Application.candidate_id"
    )
    profile = db.relationship(
        "CandidateProfile", back_populates="candidate", uselist=False,
        cascade="all, delete-orphan"
    )
    resumes = db.relationship(
        "Resume", back_populates="candidate", cascade="all, delete-orphan",
        order_by="Resume.uploaded_at.desc()"
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class CandidateProfile(db.Model):
    __tablename__ = "candidate_profiles"

    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    phone = db.Column(db.String(40), nullable=True)
    location = db.Column(db.String(150), nullable=True)
    headline = db.Column(db.String(180), nullable=True)
    education = db.Column(db.Text, nullable=True)
    experience = db.Column(db.Text, nullable=True)
    skills = db.Column(db.Text, nullable=True)
    linkedin_url = db.Column(db.String(255), nullable=True)
    portfolio_url = db.Column(db.String(255), nullable=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=current_utc_time, onupdate=current_utc_time)

    candidate = db.relationship("User", back_populates="profile")


class Resume(db.Model):
    __tablename__ = "resumes"

    id = db.Column(db.Integer, primary_key=True)
    candidate_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    original_filename = db.Column(db.String(255), nullable=False)
    stored_filename = db.Column(db.String(255), unique=True, nullable=False)
    uploaded_at = db.Column(db.DateTime, nullable=False, default=current_utc_time)
    is_primary = db.Column(db.Boolean, nullable=False, default=False)

    candidate = db.relationship("User", back_populates="resumes")
    application_links = db.relationship("ApplicationResume", back_populates="resume")


class Job(db.Model):
    __tablename__ = "jobs"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    company = db.Column(db.String(150), nullable=False)
    location = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=False)
    required_skills = db.Column(db.String(500), nullable=False)
    employer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=current_utc_time)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    employer = db.relationship("User", back_populates="jobs", foreign_keys=[employer_id])
    applications = db.relationship("Application", back_populates="job", cascade="all, delete-orphan")


class Application(db.Model):
    __tablename__ = "applications"

    id = db.Column(db.Integer, primary_key=True)
    candidate_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    job_id = db.Column(db.Integer, db.ForeignKey("jobs.id"), nullable=False, index=True)
    cover_letter = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(30), nullable=False, default="Submitted")
    applied_at = db.Column(db.DateTime, nullable=False, default=current_utc_time)

    candidate = db.relationship("User", back_populates="applications", foreign_keys=[candidate_id])
    job = db.relationship("Job", back_populates="applications")
    resume_link = db.relationship(
        "ApplicationResume", back_populates="application", uselist=False,
        cascade="all, delete-orphan"
    )

    __table_args__ = (
        db.UniqueConstraint("candidate_id", "job_id", name="uq_candidate_job_application"),
    )


class ApplicationResume(db.Model):
    """Snapshot of which candidate-owned resume was submitted with an application."""
    __tablename__ = "application_resumes"

    application_id = db.Column(
        db.Integer, db.ForeignKey("applications.id", ondelete="CASCADE"), primary_key=True
    )
    resume_id = db.Column(db.Integer, db.ForeignKey("resumes.id"), nullable=False, index=True)
    submitted_at = db.Column(db.DateTime, nullable=False, default=current_utc_time)

    application = db.relationship("Application", back_populates="resume_link")
    resume = db.relationship("Resume", back_populates="application_links")


class SavedJob(db.Model):
    __tablename__ = "saved_jobs"
    id = db.Column(db.Integer, primary_key=True)
    candidate_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    job_id = db.Column(db.Integer, db.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    saved_at = db.Column(db.DateTime, nullable=False, default=current_utc_time)
    candidate = db.relationship("User")
    job = db.relationship("Job")
    __table_args__ = (db.UniqueConstraint("candidate_id", "job_id", name="uq_saved_job_candidate_job"),)


class Notification(db.Model):
    __tablename__ = "notifications"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = db.Column(db.String(160), nullable=False)
    message = db.Column(db.String(500), nullable=False)
    target_url = db.Column(db.String(500), nullable=True)
    is_read = db.Column(db.Boolean, nullable=False, default=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=current_utc_time)


class ApplicationStatusHistory(db.Model):
    __tablename__ = "application_status_history"
    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(db.Integer, db.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True)
    changed_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    old_status = db.Column(db.String(30), nullable=True)
    new_status = db.Column(db.String(30), nullable=False)
    note = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=current_utc_time)


class Interview(db.Model):
    __tablename__ = "interviews"
    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(db.Integer, db.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True)
    scheduled_at = db.Column(db.DateTime, nullable=False)
    meeting_details = db.Column(db.String(1000), nullable=False)
    status = db.Column(db.String(30), nullable=False, default="Scheduled")
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=current_utc_time)
