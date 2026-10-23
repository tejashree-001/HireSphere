from flask import Blueprint, render_template, request, abort, current_app
from flask_login import current_user
from sqlalchemy import select, or_

from app.extensions import db
from app.models import Job, Application, Resume, SavedJob
from app.services.matching import get_user_resume_text, score_resume
from app.services.resumes import sync_legacy_resume

public_bp = Blueprint("public", __name__)


@public_bp.get("/")
def home():
    jobs = db.session.scalars(
        select(Job).where(Job.is_active.is_(True))
        .order_by(Job.created_at.desc()).limit(6)
    ).all()
    recommendations = []
    if current_user.is_authenticated and current_user.role == "candidate":
        sync_legacy_resume(current_user, current_app.config["UPLOAD_FOLDER"])
        resume_text = get_user_resume_text(current_user, current_app.config["UPLOAD_FOLDER"])
        if resume_text:
            recommendations = [{"job": job, **score_resume(resume_text, job.required_skills)} for job in jobs]
            recommendations.sort(key=lambda item: item["score"], reverse=True)
    return render_template("index.html", jobs=jobs, recommendations=recommendations)


@public_bp.get("/jobs", endpoint="job_list")
def job_list():
    search = request.args.get("q", "").strip()
    query = select(Job).where(Job.is_active.is_(True))
    if search:
        pattern = f"%{search}%"
        query = query.where(or_(
            Job.title.ilike(pattern), Job.company.ilike(pattern),
            Job.location.ilike(pattern), Job.required_skills.ilike(pattern),
            Job.description.ilike(pattern)
        ))
    jobs = db.session.scalars(query.order_by(Job.created_at.desc())).all()
    return render_template("jobs/list.html", jobs=jobs, search=search)


@public_bp.get("/jobs/<int:job_id>")
def job_detail(job_id):
    job = db.session.get(Job, job_id)
    if job is None or not job.is_active:
        abort(404)
    already_applied = False
    is_saved = False
    match = None
    resumes = []
    if current_user.is_authenticated and current_user.role == "candidate":
        sync_legacy_resume(current_user, current_app.config["UPLOAD_FOLDER"])
        already_applied = db.session.scalar(select(Application.id).where(
            Application.candidate_id == current_user.id,
            Application.job_id == job.id
        )) is not None
        is_saved = db.session.scalar(select(SavedJob.id).where(
            SavedJob.candidate_id == current_user.id, SavedJob.job_id == job.id
        )) is not None
        resumes = db.session.scalars(select(Resume).where(
            Resume.candidate_id == current_user.id
        ).order_by(Resume.is_primary.desc(), Resume.uploaded_at.desc())).all()
        resume_text = get_user_resume_text(current_user, current_app.config["UPLOAD_FOLDER"])
        if resume_text:
            match = score_resume(resume_text, job.required_skills)
    return render_template("jobs/detail.html", job=job,
                           already_applied=already_applied, is_saved=is_saved,
                           match=match, resumes=resumes)
