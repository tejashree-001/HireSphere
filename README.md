# HireSphere — AI Resume Screening & Job Recommendation Website

HireSphere is a Flask + MySQL website with separate candidate and employer accounts.

## Included features

- Candidate and employer registration/login with hashed passwords.
- Employer job posting and applicant management.
- Candidate profile with phone, location, headline, education, skills, experience, LinkedIn and portfolio details.
- Multiple candidate resumes (PDF/DOCX), primary-resume selection, private download and safe deletion rules.
- Each application stores the resume selected by the candidate; employers see the submitted resume rather than a different current resume.
- Resume text extraction using `pypdf` and `python-docx`.
- Explainable resume-to-job skill matching, missing/matched skill display, and ranked recommendations.
- Candidate application submission with a selected resume and cover letter, plus application-status tracking.
- Employer applicant review including candidate profile, cover letter, skill match, submitted resume download, and status decisions: Submitted, Reviewing, Shortlisted, Interview, Hired or Rejected.
- Saved jobs, in-app notifications, status-change history, interview scheduling, employer hiring analytics, and an admin moderation dashboard.
- Password reset links and email alerts for application submission, status changes and interviews when SMTP settings are configured.
- TF-IDF cosine similarity combined with skill overlap for ranked recommendations (transparent baseline, not a trained hiring classifier).
- CSRF protection, file-size limits, health checks, and environment-based configuration.

**Important:** the match score is a transparent skill-overlap baseline, not a trained hiring model. It should assist human review, not automatically reject candidates.

## 1. Open the project

Extract the ZIP. Open the `HireSphere` folder in VS Code. When updating an existing project, copy the included code files over the project but keep your existing `.env`, `.venv`, and `private_uploads` contents. Do not copy a `.venv` from another machine.

## 2. Create and activate a virtual environment (Windows PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If PowerShell blocks activation, use Command Prompt:

```bat
.venv\Scripts\activate.bat
```

## 3. Configure MySQL

Create the database if it does not already exist:

```sql
CREATE DATABASE IF NOT EXISTS hiresphere_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

Your existing `hiresphere_app` MySQL user can be reused if it already has privileges on `hiresphere_db`. Otherwise, create/grant a dedicated user using your own password.

Copy `.env.example` to `.env`, then set your actual MySQL username/password and a long random `SECRET_KEY`. **Do not share or commit `.env`.**

The enhanced version leaves the existing `users`, `jobs`, and `applications` tables in place and adds separate tables for candidate profiles, resumes, and the resume attached to each application. Back up your database before running the table setup command.

## 4. Upgrade the database safely

After copying the enhanced code into your existing project, run this command from the project folder with `.venv` activated:

```powershell
python -m flask --app run.py init-db
```

This runs SQLAlchemy `create_all()`: it creates the new `candidate_profiles`, `resumes`, and `application_resumes` tables if missing. It does not drop or replace your existing `users`, `jobs`, or `applications` tables. Back up your database before any schema change. Older single-resume accounts are imported into the new resume list when their existing private resume file is found.

To grant admin access, first create a normal account, then run this from the project folder:

```powershell
python -m flask --app run.py promote-admin your-admin-email@example.com
```

Replace the email with the email of the account you registered. Log out and back in; the Admin link will appear. Admin accounts cannot be created through public registration.

For password reset and email alerts, configure the optional `MAIL_*` settings in `.env` with your SMTP provider. Without SMTP configuration, in-app notifications still work, but email will not be delivered.

## 5. Start the website

```powershell
python run.py
```

Open http://127.0.0.1:5000/ . Database health check: http://127.0.0.1:5000/health/db .

## 6. Main user flow

1. Register as **Employer**, log in, and post a job with comma-separated required skills.
2. Register as **Candidate** using a different email, log in, and upload a text-based PDF/DOCX resume.
3. Open **AI recommendations** or browse a job to see matched and missing skills.
4. Fill in candidate profile details and upload one or more resumes.
5. Open a job, select the resume for that application, and submit a cover letter.
6. Log in as the employer and open applicants for that job to review the candidate profile, submitted resume, cover letter, skill overlap and TF-IDF similarity; update status or schedule an interview.
7. Candidates can save jobs, view notifications and see status history/interview details. Employers can use Analytics; admins can moderate listings.

## Deployment notes

Set `SECRET_KEY`, `DATABASE_URL` (or the `DATABASE_*` variables), and `COOKIE_SECURE=1` on a production HTTPS host. Keep `private_uploads` on persistent private storage and never expose it as a static directory. Use a production WSGI server such as Gunicorn on Linux hosting; do not use Flask's development server in production. For a typical deployment, add `gunicorn` to requirements and configure the host's start command as `gunicorn run:app`.
