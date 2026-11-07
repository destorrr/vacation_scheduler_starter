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
        organization_link = f"/organizations/{allowed_org_id}"
        assert organization_link in home.text
        organization_page = client.get(organization_link)
        assert organization_page.status_code == 200
        assert f"CI Allowed {suffix}" in organization_page.text
        assert "Организация" in organization_page.text
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

        # Employees must be created by the actual template upload, not pre-seeded.
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
            imported_employees = db.scalars(
                select(Employee).where(Employee.organization_id == organization_id)
            ).all()
            expected_names = {normalize_person_name(row["employee_name"]) for row in parsed}
            assert {normalize_person_name(item.full_name) for item in imported_employees} == expected_names
            target_employee = next(
                item for item in imported_employees
                if normalize_person_name(item.full_name) == normalize_person_name(target_name)
            )
            target_employee_id = target_employee.id
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



def test_responsible_can_ignore_non_employee_template_row():
    """The UI must offer and persist the explicit ignore action for non-employee rows."""
    from app.models.entities import Campaign, CampaignOrganization, TemplateFile, TemplateRow

    suffix = uuid4().hex[:10]
    password = "Integration-Test-Password-2026!"
    with SessionLocal() as db:
        responsible = User(
            username=f"ci-ignore-{suffix}",
            full_name="CI Ignore Responsible",
            password_hash=hash_password(password),
            role="responsible",
            is_active=True,
        )
        organization = Organization(name=f"CI Ignore Organization {suffix}")
        db.add_all([responsible, organization])
        db.flush()
        db.add(UserOrganization(user_id=responsible.id, organization_id=organization.id))
        campaign = Campaign(
            year=2075,
            name="CI ignore workflow",
            status="draft",
            created_by=responsible.id,
        )
        db.add(campaign)
        db.flush()
        campaign_org = CampaignOrganization(
            campaign_id=campaign.id,
            organization_id=organization.id,
            status="imported",
        )
        db.add(campaign_org)
        db.flush()
        template = TemplateFile(
            campaign_organization_id=campaign_org.id,
            organization_id=organization.id,
            original_filename="reference.xlsx",
            storage_path="/tmp/reference.xlsx",
            sha256=uuid4().hex + uuid4().hex,
            version_number=1,
            is_current=True,
            uploaded_by=responsible.id,
        )
        db.add(template)
        db.flush()
        row = TemplateRow(
            template_file_id=template.id,
            sheet_name="TDSheet",
            row_number=12,
            department_name="Администрация",
            position_name="Заголовок",
            employee_name=None,
            personnel_number=None,
            mapping_status="unmatched",
        )
        db.add(row)
        db.flush()
        campaign_org_id = campaign_org.id
        row_id = row.id
        db.commit()

    with TestClient(app) as client:
        _login(client, f"ci-ignore-{suffix}", password)
        page = client.get(f"/campaign-organizations/{campaign_org_id}")
        assert page.status_code == 200
        assert "Не включать строку в график" in page.text
        response = client.post(
            f"/template-rows/{row_id}/ignore",
            data={"csrf_token": _csrf_token(page)},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == f"/campaign-organizations/{campaign_org_id}"
        refreshed = client.get(f"/campaign-organizations/{campaign_org_id}")
        assert refreshed.status_code == 200
        assert "Исключено из графика" in refreshed.text

        vacations = client.get(f"/campaign-organizations/{campaign_org_id}/vacations")
        assert vacations.status_code == 200
        assert "несопоставленных строк: 0" not in vacations.text

    with SessionLocal() as db:
        saved_row = db.get(TemplateRow, row_id)
        assert saved_row.mapping_status == "ignored"
        assert saved_row.employee_id is None


def test_existing_template_rows_can_be_auto_mapped_without_reupload():
    """An already uploaded template can be repaired in place after deploying the fix."""
    from app.models.entities import (
        Campaign, CampaignOrganization, Employee, TemplateFile, TemplateRow,
    )

    suffix = uuid4().hex[:10]
    password = "Integration-Test-Password-2026!"
    full_name = "Смирнова Марина Викторовна"
    annotated_names = [
        "Смирнова Марина Викторовна (внутр.совм.)",
        "СМИРНОВА, Марина Викторовна (внешн.совм.)",
    ]
    with SessionLocal() as db:
        user = User(
            username=f"ci-remap-{suffix}",
            full_name="CI Existing Template Responsible",
            password_hash=hash_password(password),
            role="central_hr",
            is_active=True,
        )
        organization = Organization(name=f"CI Existing Template Org {suffix}")
        db.add_all([user, organization])
        db.flush()
        campaign = Campaign(
            year=2000 + int(suffix[:4], 16) % 200,
            name=f"CI Existing Template Campaign {suffix}",
            status="draft",
            created_by=user.id,
        )
        db.add(campaign)
        db.flush()
        campaign_org = CampaignOrganization(
            campaign_id=campaign.id,
            organization_id=organization.id,
            status="imported",
        )
        db.add(campaign_org)
        db.flush()
        template = TemplateFile(
            campaign_organization_id=campaign_org.id,
            organization_id=organization.id,
            original_filename="already-uploaded.xlsx",
            storage_path="/tmp/already-uploaded.xlsx",
            sha256=uuid4().hex + uuid4().hex,
            version_number=1,
            is_current=True,
            uploaded_by=user.id,
        )
        db.add(template)
        db.flush()
        for index, name in enumerate(annotated_names, start=2):
            db.add(TemplateRow(
                template_file_id=template.id,
                sheet_name="TDSheet",
                row_number=index,
                department_name="Бухгалтерия",
                position_name="Бухгалтер" if index == 2 else "Главный бухгалтер",
                employee_name=name,
                personnel_number=f"00{index}",
                mapping_status="unmatched",
            ))
        campaign_org_id = campaign_org.id
        organization_id = organization.id
        db.commit()

    with TestClient(app) as client:
        _login(client, f"ci-remap-{suffix}", password)
        page = client.get(f"/campaign-organizations/{campaign_org_id}")
        assert page.status_code == 200
        assert "Автоматически создать и сопоставить" in page.text
        response = client.post(
            f"/campaign-organizations/{campaign_org_id}/auto-map-employees",
            data={"csrf_token": _csrf_token(page)},
            follow_redirects=False,
        )
        assert response.status_code == 303

    with SessionLocal() as db:
        employees = db.scalars(
            select(Employee).where(Employee.organization_id == organization_id)
        ).all()
        assert len(employees) == 1
        assert employees[0].full_name == full_name
        rows = db.scalars(
            select(TemplateRow).where(
                TemplateRow.template_file_id == template.id
            ).order_by(TemplateRow.row_number)
        ).all()
        assert len(rows) == 2
        assert all(row.mapping_status == "matched" for row in rows)
        assert all(row.employee_id == employees[0].id for row in rows)
        assert [row.employee_name for row in rows] == [full_name, full_name]
