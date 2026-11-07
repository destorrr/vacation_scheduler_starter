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
        assert "CI Responsible" in admin_page.text

        # Create a real campaign through the same form endpoint used by the UI.
        campaigns_page = client.get("/campaigns")
        campaign_response = client.post(
            "/campaigns",
            data={
                "year": "2028",
                "name": "CI integration campaign",
                "organization_ids": [str(allowed_org_id)],
                "csrf_token": _csrf_token(campaigns_page),
            },
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



def test_reference_t7_http_upload_vacation_entry_and_excel_download(tmp_path):
    """Run the real T-7 workbook through upload, matching, period entry and download."""
    from collections import defaultdict
    from datetime import date
    from hashlib import sha256
    from io import BytesIO
    from pathlib import Path

    from openpyxl import load_workbook

    from app.excel.importer import parse_workbook
    from app.main import normalize_person_name
    from app.models.entities import (
        CampaignOrganization, Employee, ExportFile, TemplateFile, TemplateRow,
        VacationPeriod, VacationPlan,
    )

    template_path = Path(__file__).resolve().parents[2] / "ГРАФИК ОТПУСКОВ ООО  2026.xlsx"
    template_bytes = template_path.read_bytes()
    original_digest = sha256(template_bytes).hexdigest()
    parsed = parse_workbook(template_path)

    grouped = defaultdict(list)
    for row in parsed:
        grouped[normalize_person_name(row["employee_name"])].append(row)
    target_group = next(
        (rows for name, rows in grouped.items()
         if name and len(rows) > 1
         and len({row["personnel_number"] for row in rows}) > 1),
        None,
    )
    assert target_group, "The reference workbook must include a person with multiple personnel numbers"
    target_name = target_group[0]["employee_name"]
    target_rows = [row for row in target_group]

    suffix = uuid4().hex[:10]
    username = f"ci-t7-{suffix}"
    password = "Integration-Test-Password-2026!"
    with SessionLocal() as db:
        admin = User(
            username=username,
            full_name="CI T7 Central HR",
            password_hash=hash_password(password),
            role="central_hr",
            is_active=True,
        )
        organization = Organization(name=f"CI T7 Organization {suffix}")
        db.add_all([admin, organization])
        db.flush()

        # Pre-create one employee per distinct normalized FIO in this legal entity.
        employee_by_name = {}
        for row in parsed:
            normalized = normalize_person_name(row["employee_name"])
            if normalized and normalized not in employee_by_name:
                employee = Employee(
                    organization_id=organization.id,
                    full_name=row["employee_name"],
                    is_active=True,
                )
                db.add(employee)
                employee_by_name[normalized] = employee
        db.flush()
        target_employee_id = employee_by_name[normalize_person_name(target_name)].id
        organization_id = organization.id
        db.commit()

    with TestClient(app) as client:
        _login(client, username, password)

        campaign_page = client.get("/campaigns")
        created_campaign = client.post(
            "/campaigns",
            data={
                "year": "2091",
                "name": "CI real T-7 workflow",
                "organization_ids": [str(organization_id)],
                "csrf_token": _csrf_token(campaign_page),
            },
            follow_redirects=False,
        )
        assert created_campaign.status_code == 303

        with SessionLocal() as db:
            campaign_org = db.scalar(
                select(CampaignOrganization).where(
                    CampaignOrganization.organization_id == organization_id
                )
            )
            campaign_org_id = campaign_org.id

        upload_page = client.get(f"/campaign-organizations/{campaign_org_id}")
        uploaded = client.post(
            f"/campaign-organizations/{campaign_org_id}/template",
            data={"csrf_token": _csrf_token(upload_page)},
            files={
                "file": (
                    "ГРАФИК ОТПУСКОВ ООО  2026.xlsx",
                    template_bytes,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
            follow_redirects=False,
        )
        assert uploaded.status_code == 303

        with SessionLocal() as db:
            template = db.scalar(
                select(TemplateFile).where(
                    TemplateFile.campaign_organization_id == campaign_org_id,
                    TemplateFile.is_current.is_(True),
                )
            )
            assert template is not None
            template_id = template.id
            mapped_rows = db.scalars(
                select(TemplateRow).where(
                    TemplateRow.template_file_id == template_id,
                    TemplateRow.employee_id == target_employee_id,
                    TemplateRow.mapping_status == "matched",
                ).order_by(TemplateRow.row_number)
            ).all()
            assert len(mapped_rows) == len(target_rows)
            assert {row.personnel_number for row in mapped_rows} == {
                row["personnel_number"] for row in target_rows
            }

        vacations_page = client.get(
            f"/campaign-organizations/{campaign_org_id}/vacations"
        )
        assert vacations_page.status_code == 200
        csrf = _csrf_token(vacations_page)
        for start, end in (("2027-03-01", "2027-03-14"), ("2027-09-01", "2027-09-07")):
            response = client.post(
                f"/campaign-organizations/{campaign_org_id}/employees/{target_employee_id}/periods",
                data={"start_date": start, "end_date": end, "csrf_token": csrf},
                follow_redirects=False,
            )
            assert response.status_code == 303

        with SessionLocal() as db:
            plans = db.scalars(
                select(VacationPlan).where(
                    VacationPlan.campaign_organization_id == campaign_org_id,
                    VacationPlan.employee_id == target_employee_id,
                )
            ).all()
            assert len(plans) == 1
            periods = db.scalars(
                select(VacationPeriod).where(
                    VacationPeriod.vacation_plan_id == plans[0].id
                ).order_by(VacationPeriod.start_date)
            ).all()
            assert [(p.start_date, p.end_date, p.duration_days) for p in periods] == [
                (date(2027, 3, 1), date(2027, 3, 14), 14),
                (date(2027, 9, 1), date(2027, 9, 7), 7),
            ]

        export_page = client.get(
            f"/campaign-organizations/{campaign_org_id}/vacations"
        )
        exported = client.post(
            f"/campaign-organizations/{campaign_org_id}/export",
            data={"csrf_token": _csrf_token(export_page)},
            follow_redirects=False,
        )
        assert exported.status_code == 303

        with SessionLocal() as db:
            export = db.scalar(
                select(ExportFile).where(
                    ExportFile.campaign_organization_id == campaign_org_id
                )
            )
            assert export is not None
            export_id = export.id

        downloaded = client.get(f"/exports/{export_id}/download")
        assert downloaded.status_code == 200
        result_wb = load_workbook(BytesIO(downloaded.content), data_only=False)
        result_ws = result_wb["TDSheet"]
        for row in target_rows:
            row_number = row["row_number"]
            assert result_ws[f"D{row_number}"].value == row["personnel_number"]
            assert result_ws[f"E{row_number}"].value == 21
            assert result_ws[f"G{row_number}"].value == (
                "01.03.2027 (14) 01.09.2027 (7)"
            )
            assert f"E{row_number}:F{row_number}" in {
                str(item) for item in result_ws.merged_cells.ranges
            }
        result_wb.close()

    # The uploaded original is stored as a separate immutable file.
    with SessionLocal() as db:
        saved_template = db.get(TemplateFile, template_id)
        assert Path(saved_template.storage_path).read_bytes() == template_bytes
    assert sha256(template_path.read_bytes()).hexdigest() == original_digest
