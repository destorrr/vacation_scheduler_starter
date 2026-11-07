import re
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import inspect, select

from app.database import SessionLocal, engine
from app.main import app
from app.models.entities import Organization, User, UserOrganization
from app.security import hash_password


def _csrf_token(response) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
    assert match, "CSRF token must be present in the rendered form"
    return match.group(1)


def _login(client: TestClient, username: str, password: str) -> None:
    page = client.get("/login")
    assert page.status_code == 200
    response = client.post(
        "/login",
        data={
            "username": username,
            "password": password,
            "csrf_token": _csrf_token(page),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/"


def test_postgres_migrations_and_authenticated_http_workflow():
    """Exercise the migrated PostgreSQL schema and the real FastAPI request flow."""
    inspector = inspect(engine)
    expected_tables = {
        "organizations", "users", "user_organizations", "employees", "campaigns",
        "campaign_organizations", "template_files", "template_rows", "vacation_plans",
        "vacation_periods", "export_files", "audit_log", "alembic_version",
    }
    assert expected_tables.issubset(set(inspector.get_table_names()))
    with engine.connect() as connection:
        revision = connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one()
    assert revision == "0002_name_is_employee_identity"

    suffix = uuid4().hex[:10]
    admin_username = f"ci-admin-{suffix}"
    responsible_username = f"ci-user-{suffix}"
    password = "Integration-Test-Password-2026!"

    with SessionLocal() as db:
        admin = User(
            username=admin_username,
            full_name="CI Central HR",
            password_hash=hash_password(password),
            role="central_hr",
            is_active=True,
        )
        org_allowed = Organization(name=f"CI Allowed {suffix}")
        org_denied = Organization(name=f"CI Denied {suffix}")
        db.add_all([admin, org_allowed, org_denied])
        db.flush()
        responsible = User(
            username=responsible_username,
            full_name="CI Responsible",
            password_hash=hash_password(password),
            role="responsible",
            is_active=True,
        )
        db.add(responsible)
        db.flush()
        db.add(UserOrganization(
            user_id=responsible.id,
            organization_id=org_allowed.id,
        ))
        allowed_org_id = org_allowed.id
        denied_org_id = org_denied.id
        db.commit()

    with TestClient(app) as client:
        # Unauthenticated requests are redirected to the login page.
        protected = client.get("/", follow_redirects=False)
        assert protected.status_code == 303
        assert protected.headers["location"] == "/login"

        # The initial central_hr account can authenticate and open administration.
        _login(client, admin_username, password)
        admin_page = client.get("/admin/users")
        assert admin_page.status_code == 200
        assert "CI Central HR" in admin_page.text

        # Create a real campaign through the same form endpoint used by the UI.
        campaigns_page = client.get("/campaigns")
        campaign_response = client.post(
            "/campaigns",
            data=[
                ("year", "2028"),
                ("name", "CI integration campaign"),
                ("organization_ids", str(allowed_org_id)),
                ("csrf_token", _csrf_token(campaigns_page)),
            ],
            follow_redirects=False,
        )
        assert campaign_response.status_code == 303
        assert campaign_response.headers["location"] == "/campaigns"

    # A responsible user sees only assigned organizations and cannot open HR admin.
    with TestClient(app) as client:
        _login(client, responsible_username, password)
        home = client.get("/")
        assert home.status_code == 200
        assert f"CI Allowed {suffix}" in home.text
        assert f"CI Denied {suffix}" not in home.text
        assert client.get("/admin/users").status_code == 403
        campaigns = client.get("/campaigns")
        assert campaigns.status_code == 200
        assert "CI integration campaign" in campaigns.text
