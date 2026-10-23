import os
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, abort,
    current_app, send_file
)
from flask_login import login_user, logout_user, current_user, login_required
from sqlalchemy import select, func, update
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from app.extensions import db
from app.models import (User, CandidateProfile, Resume, Job, Application, ApplicationResume,
                        SavedJob, Notification, ApplicationStatusHistory, Interview)
from app.services.matching import (
    extract_text_from_file, get_user_resume_text, recommend_jobs, score_resume, tfidf_similarity
)
from app.services.resumes import sync_legacy_resume
from app.services.mailer import send_email

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")
ALLOWED_RESUME_EXTENSIONS = {".pdf", ".docx"}
ALLOWED_STATUSES = {"Submitted", "Reviewing", "Shortlisted", "Interview", "Hired", "Rejected"}
PROFILE_FIELDS = ("phone", "location", "headline", "education", "experience", "skills", "linkedin_url", "portfolio_url")


def candidate_required():
    if current_user.role != "candidate":
        abort(403)


def employer_required():
    if current_user.role != "employer":
        abort(403)


def _upload_folder():
    return Path(current_app.config["UPLOAD_FOLDER"])


def _owned_resume(resume_id):
    resume = db.session.get(Resume, resume_id)
    if resume is None or resume.candidate_id != current_user.id:
        abort(404)
    return resume


def _valid_optional_url(value):
    if not value:
        return True
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("auth.dashboard"))
    selected_role = request.args.get("role", "candidate").strip().lower()
    if selected_role not in {"candidate", "employer"}:
        selected_role = "candidate"
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "candidate").strip().lower()
        selected_role = role if role in {"candidate", "employer"} else "candidate"
        if not name or len(name) > 100:
            flash("Enter a name containing 1 to 100 characters.", "danger")
        elif len(email) > 255 or "@" not in email or "." not in email.rsplit("@", 1)[-1]:
            flash("Enter a valid email address.", "danger")
        elif len(password) < 8:
            flash("Password must contain at least 8 characters.", "danger")
        elif role not in {"candidate", "employer"}:
            flash("Choose Candidate or Employer.", "danger")
        else:
            user = User(name=name, email=email, role=role)
            user.set_password(password)
            db.session.add(user)
            try:
                db.session.commit()
                flash("Account created successfully. Please log in.", "success")
                return redirect(url_for("auth.login"))
            except IntegrityError:
                db.session.rollback()
                flash("This email address is already registered.", "warning")
            except Exception:
                db.session.rollback()
                current_app.logger.exception("Registration failed")
                flash("Registration failed. Please try again.", "danger")
    return render_template("auth/register.html", selected_role=selected_role)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("auth.dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = db.session.scalar(select(User).where(User.email == email))
        if user and user.check_password(password):
            login_user(user)
            flash("Welcome back!", "success")
            return redirect(url_for("auth.dashboard"))
        flash("Invalid email or password.", "danger")
    return render_template("auth/login.html")


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = db.session.scalar(select(User).where(User.email == email))
        # Use the same response whether the account exists or not.
        if user:
            serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
            token = serializer.dumps(user.email, salt="hiresphere-password-reset")
            reset_url = url_for("auth.reset_password", token=token, _external=True)
            send_email(user.email, "Reset your HireSphere password",
                       f"Use this link to set a new password within 1 hour:\n\n{reset_url}\n\nIf you did not request this, ignore this email.")
        flash("If an account exists for that email and email delivery is configured, a password reset link will be sent.", "info")
        return redirect(url_for("auth.login"))
    return render_template("auth/forgot_password.html")


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
    try:
        email = serializer.loads(token, salt="hiresphere-password-reset", max_age=3600)
    except (BadSignature, SignatureExpired):
        flash("That password reset link is invalid or expired. Request a new one.", "danger")
        return redirect(url_for("auth.forgot_password"))
    user = db.session.scalar(select(User).where(User.email == email))
    if user is None:
        flash("That password reset link is invalid or expired. Request a new one.", "danger")
        return redirect(url_for("auth.forgot_password"))
    if request.method == "POST":
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        if len(password) < 8:
            flash("Password must contain at least 8 characters.", "danger")
        elif password != confirm:
            flash("Passwords do not match.", "danger")
        else:
            user.set_password(password)
            db.session.commit()
            flash("Your password has been reset. Please log in.", "success")
            return redirect(url_for("auth.login"))
    return render_template("auth/reset_password.html")


@auth_bp.get("/dashboard")
@login_required
def dashboard():
    if current_user.role == "admin":
        return redirect(url_for("auth.admin_dashboard"))
    if current_user.role == "employer":
        my_jobs = db.session.scalars(
            select(Job).where(Job.employer_id == current_user.id).order_by(Job.created_at.desc())
        ).all()
        total_applications = db.session.scalar(
            select(func.count(Application.id)).join(Job, Application.job_id == Job.id)
            .where(Job.employer_id == current_user.id)
        ) or 0
        status_counts = {}
        for status in ALLOWED_STATUSES:
            status_counts[status] = db.session.scalar(
                select(func.count(Application.id)).join(Job, Application.job_id == Job.id)
                .where(Job.employer_id == current_user.id, Application.status == status)
            ) or 0
        return render_template(
            "auth/employer_dashboard.html", my_jobs=my_jobs,
            total_applications=total_applications, status_counts=status_counts
        )

    sync_legacy_resume(current_user, _upload_folder())
    my_applications = db.session.scalars(
        select(Application).where(Application.candidate_id == current_user.id)
        .order_by(Application.applied_at.desc())
    ).all()
    resume_text = get_user_resume_text(current_user, str(_upload_folder()))
    all_jobs = db.session.scalars(
        select(Job).where(Job.is_active.is_(True)).order_by(Job.created_at.desc())
    ).all()
    recommendations = recommend_jobs(resume_text, all_jobs, limit=4) if resume_text else []
    profile = current_user.profile or CandidateProfile(user_id=current_user.id)
    return render_template(
        "auth/candidate_dashboard.html", my_applications=my_applications,
        recommendations=recommendations, resume_available=bool(current_user.resume_filename),
        resume_readable=bool(resume_text), resumes=current_user.resumes, profile=profile
    )


@auth_bp.post("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("public.home"))


@auth_bp.route("/profile", methods=["GET", "POST"])
@login_required
def edit_profile():
    candidate_required()
    profile = current_user.profile
    if profile is None:
        profile = CandidateProfile(user_id=current_user.id)
        db.session.add(profile)
    if request.method == "POST":
        values = {field: request.form.get(field, "").strip() for field in PROFILE_FIELDS}
        limits = {"phone": 40, "location": 150, "headline": 180,
                  "linkedin_url": 255, "portfolio_url": 255}
        if any(len(values[field]) > max_len for field, max_len in limits.items()):
            flash("One or more profile fields are too long.", "danger")
        elif not _valid_optional_url(values["linkedin_url"]) or not _valid_optional_url(values["portfolio_url"]):
            flash("LinkedIn and portfolio links must start with http:// or https://.", "danger")
        else:
            for field, value in values.items():
                setattr(profile, field, value or None)
            try:
                db.session.commit()
                flash("Your profile details have been saved.", "success")
                return redirect(url_for("auth.edit_profile"))
            except Exception:
                db.session.rollback()
                current_app.logger.exception("Candidate profile update failed")
                flash("Your profile could not be saved. Please try again.", "danger")
    return render_template("auth/profile.html", profile=profile)


@auth_bp.route("/jobs/new", methods=["GET", "POST"])
@login_required
def create_job():
    employer_required()
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        company = request.form.get("company", "").strip()
        location = request.form.get("location", "").strip()
        description = request.form.get("description", "").strip()
        required_skills = request.form.get("required_skills", "").strip()
        if not all([title, company, location, description, required_skills]):
            flash("Please fill in every field.", "danger")
        elif len(title) > 150 or len(company) > 150 or len(location) > 150 or len(required_skills) > 500:
            flash("One or more fields exceed the allowed length.", "danger")
        else:
            job = Job(title=title, company=company, location=location,
                      description=description, required_skills=required_skills,
                      employer_id=current_user.id)
            db.session.add(job)
            try:
                db.session.commit()
                flash("Job posted successfully!", "success")
                return redirect(url_for("auth.dashboard"))
            except Exception:
                db.session.rollback()
                current_app.logger.exception("Job creation failed")
                flash("Could not save the job. Please try again.", "danger")
    return render_template("jobs/create.html")


@auth_bp.post("/jobs/<int:job_id>/apply")
@login_required
def apply_for_job(job_id):
    candidate_required()
    job = db.session.get(Job, job_id)
    if job is None or not job.is_active:
        abort(404)
    sync_legacy_resume(current_user, _upload_folder())
    cover_letter = request.form.get("cover_letter", "").strip()
    resume_id_raw = request.form.get("resume_id", "").strip()
    if not cover_letter:
        flash("Please write a cover letter before applying.", "danger")
        return redirect(url_for("public.job_detail", job_id=job.id))
    if not resume_id_raw:
        flash("Upload a resume and select it before applying.", "warning")
        return redirect(url_for("public.job_detail", job_id=job.id))
    try:
        resume_id = int(resume_id_raw)
    except ValueError:
        abort(400)
    resume = db.session.get(Resume, resume_id)
    if resume is None or resume.candidate_id != current_user.id:
        abort(403)
    existing = db.session.scalar(select(Application.id).where(
        Application.candidate_id == current_user.id, Application.job_id == job.id
    ))
    if existing:
        flash("You have already applied for this job.", "warning")
        return redirect(url_for("public.job_detail", job_id=job.id))
    application = Application(candidate_id=current_user.id, job_id=job.id, cover_letter=cover_letter)
    db.session.add(application)
    try:
        db.session.flush()
        db.session.add(ApplicationResume(application_id=application.id, resume_id=resume.id))
        db.session.add(ApplicationStatusHistory(
            application_id=application.id, changed_by_user_id=current_user.id,
            old_status=None, new_status="Submitted", note="Application submitted"
        ))
        db.session.add(Notification(
            user_id=job.employer_id, title="New job application",
            message=f"{current_user.name} applied for {job.title}.",
            target_url=url_for("auth.view_applicants", job_id=job.id)
        ))
        db.session.add(Notification(
            user_id=current_user.id, title="Application submitted",
            message=f"Your application for {job.title} at {job.company} was submitted.",
            target_url=url_for("auth.my_applications")
        ))
        db.session.commit()
        send_email(job.employer.email, f"New HireSphere application: {job.title}",
                   f"{current_user.name} ({current_user.email}) applied for {job.title}. Log in to HireSphere to review the applicant.")
        send_email(current_user.email, f"Application submitted: {job.title}",
                   f"Your application for {job.title} at {job.company} was submitted successfully.")
        flash("Your application and selected resume were submitted successfully.", "success")
        return redirect(url_for("auth.my_applications"))
    except IntegrityError:
        db.session.rollback()
        flash("You have already applied for this job.", "warning")
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Job application failed")
        flash("Your application could not be submitted.", "danger")
    return redirect(url_for("public.job_detail", job_id=job.id))


@auth_bp.get("/applications")
@login_required
def my_applications():
    candidate_required()
    applications = db.session.scalars(
        select(Application).where(Application.candidate_id == current_user.id)
        .order_by(Application.applied_at.desc())
    ).all()
    histories = {}
    interviews = {}
    for application in applications:
        histories[application.id] = db.session.scalars(
            select(ApplicationStatusHistory).where(
                ApplicationStatusHistory.application_id == application.id
            ).order_by(ApplicationStatusHistory.created_at.desc())
        ).all()
        interviews[application.id] = db.session.scalars(
            select(Interview).where(Interview.application_id == application.id)
            .order_by(Interview.scheduled_at.desc())
        ).all()
    return render_template("applications/mine.html", applications=applications,
                           histories=histories, interviews=interviews)


@auth_bp.get("/recommendations")
@login_required
def recommendations_page():
    candidate_required()
    sync_legacy_resume(current_user, _upload_folder())
    resume_text = get_user_resume_text(current_user, str(_upload_folder()))
    jobs = db.session.scalars(
        select(Job).where(Job.is_active.is_(True)).order_by(Job.created_at.desc())
    ).all()
    recommendations = recommend_jobs(resume_text, jobs, limit=20) if resume_text else []
    return render_template("recommendations.html", recommendations=recommendations,
                           resume_readable=bool(resume_text))


@auth_bp.get("/jobs/<int:job_id>/applicants")
@login_required
def view_applicants(job_id):
    employer_required()
    job = db.session.get(Job, job_id)
    if job is None or job.employer_id != current_user.id:
        abort(404)
    applications = db.session.scalars(
        select(Application).where(Application.job_id == job.id)
        .order_by(Application.applied_at.desc())
    ).all()
    screened = []
    for application in applications:
        candidate = application.candidate
        profile = candidate.profile
        submitted_resume = application.resume_link.resume if application.resume_link else None
        resume_filename = submitted_resume.stored_filename if submitted_resume else candidate.resume_filename
        resume_text = ""
        if resume_filename:
            path = _upload_folder() / Path(resume_filename).name
            if path.is_file():
                try:
                    resume_text = extract_text_from_file(path)
                except Exception:
                    current_app.logger.warning("Could not extract applicant resume text", exc_info=True)
        match = score_resume(resume_text, job.required_skills) if resume_text else {
            "score": 0, "matched": [],
            "missing": [part.strip().lower() for part in job.required_skills.replace(";", ",").split(",") if part.strip()]
        }
        screened.append({
            "application": application, "profile": profile,
            "submitted_resume": submitted_resume,
            "resume_available": bool(resume_filename and (_upload_folder() / Path(resume_filename).name).is_file()),
            "resume_readable": bool(resume_text),
            "similarity": tfidf_similarity(resume_text, f"{job.title} {job.description} {job.required_skills}") if resume_text else 0,
            "ranking_score": round(match["score"] * 0.7 + (tfidf_similarity(resume_text, f"{job.title} {job.description} {job.required_skills}") if resume_text else 0) * 0.3),
            **match
        })
    screened.sort(key=lambda item: (item["ranking_score"], item["application"].applied_at), reverse=True)
    return render_template("applications/applicants.html", job=job, screened=screened)


@auth_bp.post("/applications/<int:application_id>/status")
@login_required
def update_application_status(application_id):
    employer_required()
    application = db.session.get(Application, application_id)
    if application is None:
        abort(404)
    if application.job.employer_id != current_user.id:
        abort(403)
    status = request.form.get("status", "").strip()
    if status not in ALLOWED_STATUSES:
        flash("Invalid application status.", "danger")
    else:
        old_status = application.status
        application.status = status
        try:
            if old_status != status:
                db.session.add(ApplicationStatusHistory(
                    application_id=application.id, changed_by_user_id=current_user.id,
                    old_status=old_status, new_status=status, note="Updated by employer"
                ))
                db.session.add(Notification(
                    user_id=application.candidate_id, title="Application status updated",
                    message=f"Your application for {application.job.title} is now {status}.",
                    target_url=url_for("auth.my_applications")
                ))
            db.session.commit()
            if old_status != status:
                send_email(application.candidate.email, f"HireSphere application update: {application.job.title}",
                           f"Your application for {application.job.title} is now marked {status}. Log in to HireSphere for details.")
            flash(f"Application status updated to {status}.", "success")
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Status update failed")
            flash("Could not update the application status.", "danger")
    return redirect(url_for("auth.view_applicants", job_id=application.job_id))


@auth_bp.get("/applications/<int:application_id>/resume")
@login_required
def download_applicant_resume(application_id):
    employer_required()
    application = db.session.get(Application, application_id)
    if application is None:
        abort(404)
    if application.job.employer_id != current_user.id:
        abort(403)
    submitted_resume = application.resume_link.resume if application.resume_link else None
    filename = submitted_resume.stored_filename if submitted_resume else application.candidate.resume_filename
    if not filename:
        abort(404)
    path = _upload_folder() / Path(filename).name
    if not path.is_file():
        abort(404)
    original = submitted_resume.original_filename if submitted_resume else f"candidate-resume{path.suffix}"
    return send_file(path, as_attachment=True, download_name=secure_filename(original))




@auth_bp.post("/jobs/<int:job_id>/save")
@login_required
def toggle_saved_job(job_id):
    candidate_required()
    job = db.session.get(Job, job_id)
    if job is None or not job.is_active:
        abort(404)
    saved = db.session.scalar(select(SavedJob).where(
        SavedJob.candidate_id == current_user.id, SavedJob.job_id == job.id
    ))
    if saved:
        db.session.delete(saved)
        flash("Job removed from your saved jobs.", "success")
    else:
        db.session.add(SavedJob(candidate_id=current_user.id, job_id=job.id))
        flash("Job saved for later.", "success")
    db.session.commit()
    referrer = request.referrer or ""
    safe_referrer = referrer if referrer.startswith("/") and not referrer.startswith("//") else url_for("public.job_detail", job_id=job.id)
    return redirect(safe_referrer)


@auth_bp.get("/saved-jobs")
@login_required
def saved_jobs():
    candidate_required()
    saved = db.session.scalars(select(SavedJob).where(
        SavedJob.candidate_id == current_user.id
    ).order_by(SavedJob.saved_at.desc())).all()
    return render_template("saved_jobs.html", saved_jobs=saved)


@auth_bp.get("/notifications")
@login_required
def notifications_page():
    notifications = db.session.scalars(select(Notification).where(
        Notification.user_id == current_user.id
    ).order_by(Notification.created_at.desc()).limit(100)).all()
    return render_template("notifications.html", notifications=notifications)


@auth_bp.post("/notifications/<int:notification_id>/read")
@login_required
def mark_notification_read(notification_id):
    notification = db.session.get(Notification, notification_id)
    if notification is None or notification.user_id != current_user.id:
        abort(404)
    notification.is_read = True
    db.session.commit()
    target = notification.target_url or url_for("auth.notifications_page")
    if not target.startswith("/") or target.startswith("//"):
        target = url_for("auth.notifications_page")
    return redirect(target)


@auth_bp.post("/notifications/read-all")
@login_required
def mark_all_notifications_read():
    db.session.execute(update(Notification).where(
        Notification.user_id == current_user.id, Notification.is_read.is_(False)
    ).values(is_read=True))
    db.session.commit()
    flash("All notifications marked as read.", "success")
    return redirect(url_for("auth.notifications_page"))


@auth_bp.get("/analytics")
@login_required
def employer_analytics():
    employer_required()
    jobs = db.session.scalars(select(Job).where(
        Job.employer_id == current_user.id
    ).order_by(Job.created_at.desc())).all()
    rows = []
    totals = {status: 0 for status in ALLOWED_STATUSES}
    total = 0
    for job in jobs:
        counts = {}
        for status in ALLOWED_STATUSES:
            counts[status] = db.session.scalar(select(func.count(Application.id)).where(
                Application.job_id == job.id, Application.status == status
            )) or 0
            totals[status] += counts[status]
        job_total = sum(counts.values())
        total += job_total
        rows.append({"job": job, "counts": counts, "total": job_total})
    return render_template("analytics.html", rows=rows, totals=totals, total_applications=total)


@auth_bp.post("/applications/<int:application_id>/interview")
@login_required
def schedule_interview(application_id):
    employer_required()
    application = db.session.get(Application, application_id)
    if application is None or application.job.employer_id != current_user.id:
        abort(404)
    date_text = request.form.get("scheduled_at", "").strip()
    details = request.form.get("meeting_details", "").strip()
    try:
        scheduled_at = datetime.strptime(date_text, "%Y-%m-%dT%H:%M")
    except ValueError:
        flash("Choose a valid interview date and time.", "danger")
        return redirect(url_for("auth.view_applicants", job_id=application.job_id))
    if scheduled_at <= datetime.now():
        flash("Interview must be scheduled for a future date and time.", "danger")
    elif not details or len(details) > 1000:
        flash("Enter interview details or a meeting link (maximum 1000 characters).", "danger")
    else:
        interview = Interview(application_id=application.id, scheduled_at=scheduled_at,
                              meeting_details=details, created_by_user_id=current_user.id)
        db.session.add(interview)
        if application.status != "Interview":
            old_status = application.status
            application.status = "Interview"
            db.session.add(ApplicationStatusHistory(
                application_id=application.id, changed_by_user_id=current_user.id,
                old_status=old_status, new_status="Interview", note="Interview scheduled"
            ))
        db.session.add(Notification(
            user_id=application.candidate_id, title="Interview scheduled",
            message=f"An interview for {application.job.title} is scheduled for {scheduled_at.strftime('%d %b %Y at %H:%M')}.",
            target_url=url_for("auth.my_applications")
        ))
        try:
            db.session.commit()
            send_email(application.candidate.email, f"Interview scheduled: {application.job.title}",
                       f"An interview for {application.job.title} is scheduled for {scheduled_at.strftime('%d %b %Y at %H:%M')}. Details: {details}")
            flash("Interview scheduled and candidate notified.", "success")
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Interview scheduling failed")
            flash("Could not schedule the interview.", "danger")
    return redirect(url_for("auth.view_applicants", job_id=application.job_id))


@auth_bp.get("/admin")
@login_required
def admin_dashboard():
    if current_user.role != "admin":
        abort(403)
    users = db.session.scalars(select(User).order_by(User.created_at.desc())).all()
    jobs = db.session.scalars(select(Job).order_by(Job.created_at.desc())).all()
    stats = {
        "users": db.session.scalar(select(func.count(User.id))) or 0,
        "candidates": db.session.scalar(select(func.count(User.id)).where(User.role == "candidate")) or 0,
        "employers": db.session.scalar(select(func.count(User.id)).where(User.role == "employer")) or 0,
        "jobs": db.session.scalar(select(func.count(Job.id))) or 0,
        "applications": db.session.scalar(select(func.count(Application.id))) or 0,
    }
    return render_template("admin.html", users=users, jobs=jobs, stats=stats)


@auth_bp.post("/admin/jobs/<int:job_id>/toggle")
@login_required
def admin_toggle_job(job_id):
    if current_user.role != "admin":
        abort(403)
    job = db.session.get(Job, job_id)
    if job is None:
        abort(404)
    job.is_active = not job.is_active
    db.session.commit()
    flash(f"Job listing {'activated' if job.is_active else 'deactivated'}.", "success")
    return redirect(url_for("auth.admin_dashboard"))


@auth_bp.post("/resume/upload")
@login_required
def upload_resume():
    candidate_required()
    sync_legacy_resume(current_user, _upload_folder())
    uploaded = request.files.get("resume")
    if uploaded is None or not uploaded.filename:
        flash("Please choose a resume file.", "danger")
        return redirect(url_for("auth.dashboard"))
    safe_original = secure_filename(uploaded.filename)
    extension = Path(safe_original).suffix.lower()
    if extension not in ALLOWED_RESUME_EXTENSIONS:
        flash("Upload a PDF or DOCX resume only.", "danger")
        return redirect(url_for("auth.dashboard"))
    upload_dir = _upload_folder()
    upload_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}{extension}"
    new_path = upload_dir / stored_name
    try:
        uploaded.save(new_path)
        resume_text = extract_text_from_file(new_path)
        if not resume_text.strip():
            new_path.unlink(missing_ok=True)
            flash("No selectable text was found. Please upload a text-based PDF or DOCX resume.", "danger")
            return redirect(url_for("auth.dashboard"))
        for existing_resume in current_user.resumes:
            existing_resume.is_primary = False
        resume = Resume(
            candidate_id=current_user.id, original_filename=safe_original,
            stored_filename=stored_name, is_primary=True
        )
        db.session.add(resume)
        current_user.resume_filename = stored_name
        db.session.commit()
        flash("Resume uploaded successfully. It is now your primary resume.", "success")
    except Exception:
        db.session.rollback()
        new_path.unlink(missing_ok=True)
        current_app.logger.exception("Resume upload failed")
        flash("Resume could not be read or saved. Please check the file and try again.", "danger")
    return redirect(url_for("auth.dashboard"))


@auth_bp.post("/resumes/<int:resume_id>/primary")
@login_required
def set_primary_resume(resume_id):
    candidate_required()
    resume = _owned_resume(resume_id)
    for owned in current_user.resumes:
        owned.is_primary = owned.id == resume.id
    current_user.resume_filename = resume.stored_filename
    try:
        db.session.commit()
        flash("Primary resume updated. Recommendations will use this resume.", "success")
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Primary resume update failed")
        flash("Could not update your primary resume.", "danger")
    return redirect(url_for("auth.dashboard"))


@auth_bp.get("/resumes/<int:resume_id>/download")
@login_required
def download_own_resume(resume_id):
    candidate_required()
    resume = _owned_resume(resume_id)
    path = _upload_folder() / Path(resume.stored_filename).name
    if not path.is_file():
        abort(404)
    return send_file(path, as_attachment=True, download_name=secure_filename(resume.original_filename))


@auth_bp.post("/resumes/<int:resume_id>/delete")
@login_required
def delete_resume(resume_id):
    candidate_required()
    resume = _owned_resume(resume_id)
    if resume.application_links:
        flash("This resume has been submitted with an application, so it cannot be deleted.", "warning")
        return redirect(url_for("auth.dashboard"))
    path = _upload_folder() / Path(resume.stored_filename).name
    was_primary = resume.is_primary or current_user.resume_filename == resume.stored_filename
    stored_filename = resume.stored_filename
    db.session.delete(resume)
    try:
        db.session.flush()
        if was_primary:
            next_resume = db.session.scalar(
                select(Resume).where(Resume.candidate_id == current_user.id)
                .order_by(Resume.uploaded_at.desc())
            )
            if next_resume:
                next_resume.is_primary = True
                current_user.resume_filename = next_resume.stored_filename
            else:
                current_user.resume_filename = None
        db.session.commit()
        if path.is_file():
            path.unlink(missing_ok=True)
        flash("Resume deleted.", "success")
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Resume deletion failed")
        flash("Could not delete the resume.", "danger")
    return redirect(url_for("auth.dashboard"))
