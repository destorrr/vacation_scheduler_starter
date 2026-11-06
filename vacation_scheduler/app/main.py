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
    if normalized_inn and not re.fullmatch(r"\\d{10}|\\d{12}", normalized_inn):
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
