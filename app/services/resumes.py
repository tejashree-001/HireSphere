"""Helpers for keeping older single-resume accounts compatible with multi-resume storage."""
from pathlib import Path

from sqlalchemy import select

from app.extensions import db
from app.models import Resume


def sync_legacy_resume(user, upload_folder):
    """Represent an existing users.resume_filename as a Resume row when its file exists."""
    if user.role != "candidate" or not user.resume_filename:
        return None
    stored_name = Path(user.resume_filename).name
    existing = db.session.scalar(
        select(Resume).where(Resume.candidate_id == user.id, Resume.stored_filename == stored_name)
    )
    if existing:
        return existing
    file_path = Path(upload_folder) / stored_name
    if not file_path.is_file():
        return None
    # The legacy filename was the active resume pointer; preserve it as the primary resume.
    for previous in user.resumes:
        previous.is_primary = False
    row = Resume(
        candidate_id=user.id,
        original_filename=f"Previous resume{file_path.suffix.lower()}",
        stored_filename=stored_name,
        is_primary=True,
    )
    db.session.add(row)
    db.session.commit()
    return row
