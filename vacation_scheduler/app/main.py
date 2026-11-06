import re
from uuid import UUID

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user, require_org_access, require_roles
from app.models.entities import AuditLog, Organization, User, UserOrganization
from app.security import csrf_is_valid, hash_password, new_csrf_token, verify_password

app = FastAPI(title=settings.app_name)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie="vacation_session",
    max_age=settings.session_max_age,
    same_site="lax",
    https_only=settings.session_https_only,
)
templates = Jinja2Templates(directory="app/templates")


def check_csrf(request: Request, token: str) -> None:
    if not csrf_is_valid(request.session.get("csrf_token"), token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF-проверка не пройдена.")


def audit(db: Session, actor: User, action: str, entity_id: UUID, details: dict) -> None:
    db.add(AuditLog(
        user_id=actor.id,
        action=action,
        entity_type="user",
        entity_id=entity_id,
        details=details,
    ))


# Campaigns, template import and employee-row mapping routes.
from collections import defaultdict
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4
import re
import unicodedata

from fastapi import File, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import func
from app.models.entities import (
    Campaign, CampaignOrganization, Employee, TemplateFile, TemplateRow,
)
from app.excel.importer import parse_workbook


def normalize_person_name(value: str | None) -> str:
    if not value:
        return ""
    value = unicodedata.normalize("NFKC", value).lower().replace("ё", "е")
    return " ".join(re.sub(r"[^а-яa-z0-9]+", " ", value).split())


@app.get("/campaigns", response_class=HTMLResponse)
def campaigns_page(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = (
        select(CampaignOrganization, Campaign, Organization)
        .join(Campaign, Campaign.id == CampaignOrganization.campaign_id)
        .join(Organization, Organization.id == CampaignOrganization.organization_id)
        .order_by(Campaign.year.desc(), Organization.name)
    )
    if user.role != "central_hr":
        query = query.join(
            UserOrganization, UserOrganization.organization_id == Organization.id
        ).where(UserOrganization.user_id == user.id)
    campaign_rows = db.execute(query).all()
    organizations = db.scalars(
        select(Organization).where(Organization.is_active.is_(True)).order_by(Organization.name)
    ).all() if user.role == "central_hr" else []
    return templates.TemplateResponse(
        request=request,
        name="campaigns.html",
        context={
            "app_name": settings.app_name, "user": user, "campaign_rows": campaign_rows,
            "organizations": organizations, "csrf_token": request.session["csrf_token"],
            "now_year": date.today().year,
        },
    )


@app.post("/campaigns")
def create_campaign(
    request: Request,
    year: int = Form(...),
    name: str = Form(...),
    organization_ids: list[str] = Form([]),
    csrf_token: str = Form(...),
    actor: User = Depends(require_roles("central_hr")),
    db: Session = Depends(get_db),
):
    check_csrf(request, csrf_token)
    if year < 2000 or year > 2200:
        raise HTTPException(status_code=422, detail="Год должен быть в диапазоне 2000–2200.")
    if not name.strip() or len(name.strip()) > 255:
        raise HTTPException(status_code=422, detail="Укажите название кампании.")
    if not organization_ids:
        raise HTTPException(status_code=422, detail="Выберите хотя бы одну организацию.")
    if db.scalar(select(Campaign.id).where(Campaign.year == year)):
        raise HTTPException(status_code=409, detail="Кампания на этот год уже существует.")
    try:
        selected_ids = {UUID(value) for value in organization_ids}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Некорректный идентификатор организации.") from exc
    active_ids = set(db.scalars(select(Organization.id).where(
        Organization.id.in_(selected_ids), Organization.is_active.is_(True)
    )).all())
    if active_ids != selected_ids:
        raise HTTPException(status_code=422, detail="Выбрана несуществующая или неактивная организация.")
    campaign = Campaign(year=year, name=name.strip(), status="draft", created_by=actor.id)
    db.add(campaign)
    db.flush()
    for org_id in selected_ids:
        db.add(CampaignOrganization(
            campaign_id=campaign.id, organization_id=org_id, status="pending"
        ))
    db.add(AuditLog(
        user_id=actor.id, action="campaign.created", entity_type="campaign",
        entity_id=campaign.id,
        details={"year": year, "organization_ids": [str(x) for x in selected_ids]},
    ))
    db.commit()
    return RedirectResponse("/campaigns", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/campaign-organizations/{campaign_org_id}", response_class=HTMLResponse)
def campaign_organization_page(
    campaign_org_id: UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    campaign_org = db.get(CampaignOrganization, campaign_org_id)
    if campaign_org is None:
        raise HTTPException(status_code=404, detail="Кампания организации не найдена.")
    require_org_access(campaign_org.organization_id, user, db)
    campaign = db.get(Campaign, campaign_org.campaign_id)
    organization = db.get(Organization, campaign_org.organization_id)
    current_template = db.scalar(
        select(TemplateFile).where(
            TemplateFile.campaign_organization_id == campaign_org.id,
            TemplateFile.is_current.is_(True),
        ).order_by(TemplateFile.version_number.desc())
    )
    rows = []
    if current_template:
        rows = db.scalars(
            select(TemplateRow).where(TemplateRow.template_file_id == current_template.id)
            .order_by(TemplateRow.sheet_name, TemplateRow.row_number)
        ).all()
    employees = db.scalars(
        select(Employee).where(
            Employee.organization_id == organization.id, Employee.is_active.is_(True)
        ).order_by(Employee.full_name)
    ).all()
    return templates.TemplateResponse(
        request=request, name="campaign_organization.html",
        context={
            "app_name": settings.app_name, "user": user, "campaign": campaign,
            "campaign_org": campaign_org, "organization": organization,
            "current_template": current_template, "rows": rows, "employees": employees,
            "csrf_token": request.session["csrf_token"],
        },
    )


@app.post("/campaign-organizations/{campaign_org_id}/template")
async def upload_template(
    campaign_org_id: UUID,
    request: Request,
    file: UploadFile = File(...),
    csrf_token: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    check_csrf(request, csrf_token)
    campaign_org = db.get(CampaignOrganization, campaign_org_id)
    if campaign_org is None:
        raise HTTPException(status_code=404, detail="Кампания организации не найдена.")
    require_org_access(campaign_org.organization_id, user, db)
    campaign = db.get(Campaign, campaign_org.campaign_id)
    if campaign.status in {"closed", "archived"}:
        raise HTTPException(status_code=409, detail="Кампания закрыта для изменений.")
    filename = Path(file.filename or "template.xlsx").name
    if Path(filename).suffix.lower() not in {".xlsx", ".xlsm"}:
        raise HTTPException(status_code=415, detail="Поддерживаются файлы .xlsx и .xlsm.")
    content = await file.read()
    if not content or len(content) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Файл пустой или превышает лимит 20 МБ.")
    temp_dir = Path(settings.storage_path) / "temp"
    originals_dir = Path(settings.storage_path) / "originals"
    temp_dir.mkdir(parents=True, exist_ok=True)
    originals_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / f"{uuid4().hex}.xlsx"
    temp_path.write_bytes(content)
    try:
        parsed_rows = parse_workbook(temp_path)
    except ValueError as exc:
        temp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    digest = sha256(content).hexdigest()
    duplicate = db.scalar(select(TemplateFile.id).where(
        TemplateFile.campaign_organization_id == campaign_org.id,
        TemplateFile.sha256 == digest,
    ))
    if duplicate:
        temp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=409, detail="Этот файл уже загружался в данную кампанию.")
    max_version = db.scalar(select(func.max(TemplateFile.version_number)).where(
        TemplateFile.campaign_organization_id == campaign_org.id
    )) or 0
    version = max_version + 1
    stored_name = f"{campaign_org.id}_v{version}_{uuid4().hex}{Path(filename).suffix.lower()}"
    stored_path = originals_dir / stored_name
    temp_path.replace(stored_path)
    db.query(TemplateFile).filter(
        TemplateFile.campaign_organization_id == campaign_org.id,
        TemplateFile.is_current.is_(True),
    ).update({TemplateFile.is_current: False}, synchronize_session=False)
    template = TemplateFile(
        campaign_organization_id=campaign_org.id,
        organization_id=campaign_org.organization_id,
        original_filename=filename[:255],
        storage_path=str(stored_path),
        sha256=digest,
        version_number=version,
        is_current=True,
        uploaded_by=user.id,
    )
    db.add(template)
    db.flush()
    employee_by_number = {}
    employees = db.scalars(select(Employee).where(
        Employee.organization_id == campaign_org.organization_id,
        Employee.is_active.is_(True),
    )).all()
    for employee in employees:
        if employee.personnel_number:
            employee_by_number.setdefault(employee.personnel_number.strip().casefold(), []).append(employee)
    employee_by_name = defaultdict(list)
    for employee in employees:
        employee_by_name[normalize_person_name(employee.full_name)].append(employee)

    matched_count = 0
    review_count = 0
    for row in parsed_rows:
        matches = []
        if row["personnel_number"]:
            matches = employee_by_number.get(row["personnel_number"].strip().casefold(), [])
        if not matches:
            matches = employee_by_name.get(normalize_person_name(row["employee_name"]), [])
        mapped_employee = matches[0] if len(matches) == 1 else None
        mapping_status = "matched" if mapped_employee else ("needs_review" if len(matches) > 1 else "unmatched")
        if mapped_employee:
            matched_count += 1
        elif mapping_status == "needs_review":
            review_count += 1
        db.add(TemplateRow(
            template_file_id=template.id,
            employee_id=mapped_employee.id if mapped_employee else None,
            sheet_name=row["sheet_name"],
            row_number=row["row_number"],
            department_name=row["department_name"],
            position_name=row["position_name"],
            employee_name=row["employee_name"],
            personnel_number=row["personnel_number"],
            mapping_status=mapping_status,
        ))
    campaign_org.status = "imported"
    db.add(AuditLog(
        user_id=user.id, action="template.uploaded", entity_type="template_file",
        entity_id=template.id,
        details={
            "campaign_organization_id": str(campaign_org.id),
            "version": version, "row_count": len(parsed_rows),
            "matched_count": matched_count, "needs_review_count": review_count,
        },
    ))
    db.commit()
    return RedirectResponse(
        f"/campaign-organizations/{campaign_org.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/template-rows/{row_id}/map")
def map_template_row(
    row_id: UUID,
    request: Request,
    employee_id: str = Form(...),
    csrf_token: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    check_csrf(request, csrf_token)
    row = db.get(TemplateRow, row_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Строка шаблона не найдена.")
    template = db.get(TemplateFile, row.template_file_id)
    campaign_org = db.get(CampaignOrganization, template.campaign_organization_id)
    require_org_access(campaign_org.organization_id, user, db)
    campaign = db.get(Campaign, campaign_org.campaign_id)
    if campaign.status in {"closed", "archived"}:
        raise HTTPException(status_code=409, detail="Кампания закрыта для изменений.")
    employee = db.get(Employee, UUID(employee_id))
    if employee is None or employee.organization_id != campaign_org.organization_id:
        raise HTTPException(status_code=422, detail="Выберите сотрудника из этой организации.")
    row.employee_id = employee.id
    row.mapping_status = "matched"
    db.add(AuditLog(
        user_id=user.id, action="template_row.mapped", entity_type="template_row",
        entity_id=row.id, details={"employee_id": str(employee.id)},
    ))
    db.commit()
    return RedirectResponse(
        f"/campaign-organizations/{campaign_org.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/template-rows/{row_id}/create-employee")
def create_employee_from_template_row(
    row_id: UUID,
    request: Request,
    csrf_token: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    check_csrf(request, csrf_token)
    row = db.get(TemplateRow, row_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Строка шаблона не найдена.")
    template = db.get(TemplateFile, row.template_file_id)
    campaign_org = db.get(CampaignOrganization, template.campaign_organization_id)
    require_org_access(campaign_org.organization_id, user, db)
    campaign = db.get(Campaign, campaign_org.campaign_id)
    if campaign.status in {"closed", "archived"}:
        raise HTTPException(status_code=409, detail="Кампания закрыта для изменений.")
    if row.employee_id:
        raise HTTPException(status_code=409, detail="Строка уже сопоставлена с сотрудником.")
    employee = None
    if row.personnel_number:
        employee = db.scalar(select(Employee).where(
            Employee.organization_id == campaign_org.organization_id,
            Employee.personnel_number == row.personnel_number,
        ))
    if employee is None:
        employee = Employee(
            organization_id=campaign_org.organization_id,
            personnel_number=row.personnel_number,
            full_name=row.employee_name,
            is_active=True,
        )
        db.add(employee)
        db.flush()
    row.employee_id = employee.id
    row.mapping_status = "matched"
    db.add(AuditLog(
        user_id=user.id, action="employee.created_from_template", entity_type="employee",
        entity_id=employee.id,
        details={"template_row_id": str(row.id), "personnel_number": row.personnel_number},
    ))
    db.commit()
    return RedirectResponse(
        f"/campaign-organizations/{campaign_org.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    csrf_token = new_csrf_token()
    request.session["csrf_token"] = csrf_token
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"app_name": settings.app_name, "csrf_token": csrf_token, "error": None},
    )


@app.post("/login", response_class=HTMLResponse)
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    check_csrf(request, csrf_token)
    user = db.scalar(select(User).where(User.username == username.strip().lower()))
    if user is None or not user.is_active or not verify_password(user.password_hash, password):
        token = new_csrf_token()
        request.session["csrf_token"] = token
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "app_name": settings.app_name,
                "csrf_token": token,
                "error": "Неверное имя пользователя или пароль.",
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    request.session.clear()
    request.session["user_id"] = str(user.id)
    request.session["csrf_token"] = new_csrf_token()
    return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/logout")
def logout(request: Request, csrf_token: str = Form(...)):
    check_csrf(request, csrf_token)
    request.session.clear()
    return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role == "central_hr":
        organizations = db.scalars(
            select(Organization).where(Organization.is_active.is_(True)).order_by(Organization.name)
        ).all()
    else:
        organizations = db.scalars(
            select(Organization)
            .join(UserOrganization, UserOrganization.organization_id == Organization.id)
            .where(UserOrganization.user_id == user.id, Organization.is_active.is_(True))
            .order_by(Organization.name)
        ).all()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "app_name": settings.app_name,
            "user": user,
            "organizations": organizations,
            "csrf_token": request.session["csrf_token"],
        },
    )


@app.get("/organizations/{organization_id}")
def organization_access_check(
    organization_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_org_access(organization_id, user, db)
    organization = db.get(Organization, organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Организация не найдена.")
    return {"id": str(organization.id), "name": organization.name}


@app.get("/admin/users", response_class=HTMLResponse)
def users_page(
    request: Request,
    user: User = Depends(require_roles("central_hr")),
    db: Session = Depends(get_db),
):
    users = db.scalars(
        select(User).where(User.role == "responsible").order_by(User.full_name, User.username)
    ).all()
    organizations = db.scalars(
        select(Organization).where(Organization.is_active.is_(True)).order_by(Organization.name)
    ).all()
    user_org_rows = db.execute(
        select(UserOrganization.user_id, UserOrganization.organization_id)
    ).all()
    assignments: dict[UUID, set[UUID]] = {}
    for user_id, organization_id in user_org_rows:
        assignments.setdefault(user_id, set()).add(organization_id)

    return templates.TemplateResponse(
        request=request,
        name="admin_users.html",
        context={
            "app_name": settings.app_name,
            "user": user,
            "users": users,
            "organizations": organizations,
            "assignments": assignments,
            "csrf_token": request.session["csrf_token"],
            "error": None,
            "success": request.query_params.get("saved"),
        },
    )


@app.post("/admin/organizations")
def create_organization(
    request: Request,
    name: str = Form(...),
    short_name: str = Form(""),
    inn: str = Form(""),
    csrf_token: str = Form(...),
    actor: User = Depends(require_roles("central_hr")),
    db: Session = Depends(get_db),
):
    check_csrf(request, csrf_token)
    normalized_name = name.strip()
    normalized_short_name = short_name.strip() or None
    normalized_inn = inn.strip() or None
    if not normalized_name or len(normalized_name) > 255:
        raise HTTPException(status_code=422, detail="Укажите название организации (до 255 символов).")
    if normalized_short_name and len(normalized_short_name) > 100:
        raise HTTPException(status_code=422, detail="Краткое название должно быть не длиннее 100 символов.")
    if normalized_inn and not re.fullmatch(r"\d{10}|\d{12}", normalized_inn):
        raise HTTPException(status_code=422, detail="ИНН должен содержать 10 или 12 цифр.")
    if normalized_inn and db.scalar(select(Organization.id).where(Organization.inn == normalized_inn)):
        raise HTTPException(status_code=409, detail="Организация с таким ИНН уже существует.")

    organization = Organization(
        name=normalized_name,
        short_name=normalized_short_name,
        inn=normalized_inn,
        is_active=True,
    )
    db.add(organization)
    db.flush()
    db.add(AuditLog(
        user_id=actor.id,
        action="organization.created",
        entity_type="organization",
        entity_id=organization.id,
        details={"name": normalized_name, "inn": normalized_inn},
    ))
    db.commit()
    return RedirectResponse("/admin/users?saved=organization-created", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/users")
def create_responsible(
    request: Request,
    username: str = Form(...),
    full_name: str = Form(...),
    password: str = Form(...),
    organization_ids: list[str] = Form([]),
    csrf_token: str = Form(...),
    actor: User = Depends(require_roles("central_hr")),
    db: Session = Depends(get_db),
):
    check_csrf(request, csrf_token)
    normalized_username = username.strip().lower()
    normalized_name = full_name.strip()
    if not re.fullmatch(r"[a-z0-9_.-]{3,100}", normalized_username):
        raise HTTPException(status_code=422, detail="Логин: 3–100 символов, латинские буквы, цифры, точка, дефис или подчёркивание.")
    if not normalized_name or len(normalized_name) > 255:
        raise HTTPException(status_code=422, detail="Укажите корректное ФИО.")
    if db.scalar(select(User.id).where(User.username == normalized_username)):
        raise HTTPException(status_code=409, detail="Пользователь с таким логином уже существует.")
    if not organization_ids:
        raise HTTPException(status_code=422, detail="Назначьте пользователю хотя бы одну организацию.")

    try:
        selected_ids = {UUID(value) for value in organization_ids}
        password_hash = hash_password(password)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    valid_ids = set(db.scalars(
        select(Organization.id).where(
            Organization.id.in_(selected_ids),
            Organization.is_active.is_(True),
        )
    ).all())
    if valid_ids != selected_ids:
        raise HTTPException(status_code=422, detail="Выбрана несуществующая или неактивная организация.")

    new_user = User(
        username=normalized_username,
        full_name=normalized_name,
        password_hash=password_hash,
        role="responsible",
        is_active=True,
    )
    db.add(new_user)
    db.flush()
    for organization_id in sorted(selected_ids, key=str):
        db.add(UserOrganization(user_id=new_user.id, organization_id=organization_id))
    audit(db, actor, "user.created", new_user.id, {
        "username": normalized_username,
        "organization_ids": [str(value) for value in sorted(selected_ids, key=str)],
    })
    db.commit()
    return RedirectResponse("/admin/users?saved=created", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/users/{user_id}/update")
def update_responsible(
    user_id: UUID,
    request: Request,
    full_name: str = Form(...),
    is_active: str = Form("false"),
    password: str = Form(""),
    organization_ids: list[str] = Form([]),
    csrf_token: str = Form(...),
    actor: User = Depends(require_roles("central_hr")),
    db: Session = Depends(get_db),
):
    check_csrf(request, csrf_token)
    target = db.get(User, user_id)
    if target is None or target.role != "responsible":
        raise HTTPException(status_code=404, detail="Ответственный пользователь не найден.")

    normalized_name = full_name.strip()
    if not normalized_name or len(normalized_name) > 255:
        raise HTTPException(status_code=422, detail="Укажите корректное ФИО.")
    if not organization_ids:
        raise HTTPException(status_code=422, detail="У пользователя должна остаться хотя бы одна организация.")

    try:
        selected_ids = {UUID(value) for value in organization_ids}
        new_hash = hash_password(password) if password.strip() else None
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    valid_ids = set(db.scalars(
        select(Organization.id).where(
            Organization.id.in_(selected_ids),
            Organization.is_active.is_(True),
        )
    ).all())
    if valid_ids != selected_ids:
        raise HTTPException(status_code=422, detail="Выбрана несуществующая или неактивная организация.")

    old_active = target.is_active
    old_org_ids = set(db.scalars(
        select(UserOrganization.organization_id).where(UserOrganization.user_id == target.id)
    ).all())

    target.full_name = normalized_name
    target.is_active = is_active.lower() in {"true", "1", "on", "yes"}
    if new_hash:
        target.password_hash = new_hash

    db.execute(delete(UserOrganization).where(UserOrganization.user_id == target.id))
    for organization_id in sorted(selected_ids, key=str):
        db.add(UserOrganization(user_id=target.id, organization_id=organization_id))

    audit(db, actor, "user.updated", target.id, {
        "is_active_before": old_active,
        "is_active_after": target.is_active,
        "organization_ids_before": [str(value) for value in sorted(old_org_ids, key=str)],
        "organization_ids_after": [str(value) for value in sorted(selected_ids, key=str)],
        "password_changed": bool(new_hash),
    })
    db.commit()
    return RedirectResponse("/admin/users?saved=updated", status_code=status.HTTP_303_SEE_OTHER)
