from hashlib import sha256
from io import BytesIO
from uuid import uuid4

from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models.entities import (
    Campaign, CampaignOrganization, Employee, Organization, TemplateFile,
    TemplateRow, User,
)
from app.security import hash_password


def _csrf(response):
    import re
    match = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
    assert match
    return match.group(1)


def _workbook_bytes(column_width: float) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Т-7"
    sheet.append([
        "№", "Структурное подразделение", "Должность",
        "ФИО", "Табельный номер",
    ])
    sheet.append([
        1, "Бухгалтерия", "Бухгалтер",
        "Иванов Иван Иванович", "00125",
    ])
    sheet.column_dimensions["A"].width = column_width
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def test_reupload_creates_new_immutable_template_version(tmp_path):
    suffix = uuid4().hex[:12]
    password = "Template-Version-Test-2026!"
    first_bytes = _workbook_bytes(12)
    second_bytes = _workbook_bytes(18)
    assert sha256(first_bytes).digest() != sha256(second_bytes).digest()

    with SessionLocal() as db:
        user = User(
            username=f"ci-version-{suffix}",
            full_name="CI Template Version User",
            password_hash=hash_password(password),
            role="central_hr",
            is_active=True,
        )
        organization = Organization(name=f"CI Template Version Org {suffix}")
        db.add_all([user, organization])
        db.flush()
        campaign = Campaign(
            year=2000 + (int(suffix[:6], 16) % 201),
            name=f"CI Template Version Campaign {suffix}",
            status="draft",
            created_by=user.id,
        )
        db.add(campaign)
        db.flush()
        campaign_org = CampaignOrganization(
            campaign_id=campaign.id,
            organization_id=organization.id,
            status="pending",
        )
        employee = Employee(
            organization_id=organization.id,
            full_name="Иванов Иван Иванович",
            is_active=True,
        )
        db.add_all([campaign_org, employee])
        db.commit()
        campaign_org_id = campaign_org.id
        organization_id = organization.id

    with TestClient(app) as client:
        login_page = client.get("/login")
        login = client.post(
            "/login",
            data={
                "username": f"ci-version-{suffix}",
                "password": password,
                "csrf_token": _csrf(login_page),
            },
            follow_redirects=False,
        )
        assert login.status_code == 303

        upload_page = client.get(f"/campaign-organizations/{campaign_org_id}")
        first_upload = client.post(
            f"/campaign-organizations/{campaign_org_id}/template",
            data={"csrf_token": _csrf(upload_page)},
            files={"file": (
                "template.xlsx", first_bytes,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )},
            follow_redirects=False,
        )
        assert first_upload.status_code == 303

        second_page = client.get(f"/campaign-organizations/{campaign_org_id}")
        second_upload = client.post(
            f"/campaign-organizations/{campaign_org_id}/template",
            data={"csrf_token": _csrf(second_page)},
            files={"file": (
                "template.xlsx", second_bytes,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )},
            follow_redirects=False,
        )
        assert second_upload.status_code == 303

        duplicate_page = client.get(f"/campaign-organizations/{campaign_org_id}")
        duplicate_upload = client.post(
            f"/campaign-organizations/{campaign_org_id}/template",
            data={"csrf_token": _csrf(duplicate_page)},
            files={"file": (
                "template.xlsx", second_bytes,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )},
            follow_redirects=False,
        )
        assert duplicate_upload.status_code == 409

    with SessionLocal() as db:
        versions = db.scalars(
            select(TemplateFile)
            .where(TemplateFile.campaign_organization_id == campaign_org_id)
            .order_by(TemplateFile.version_number)
        ).all()
        assert [item.version_number for item in versions] == [1, 2]
        assert [item.is_current for item in versions] == [False, True]
        assert [sha256(open(item.storage_path, "rb").read()).digest() for item in versions] == [
            sha256(first_bytes).digest(),
            sha256(second_bytes).digest(),
        ]
        current_rows = db.scalars(
            select(TemplateRow).where(TemplateRow.template_file_id == versions[1].id)
        ).all()
        assert len(current_rows) == 1
        assert current_rows[0].employee_id is not None
        assert current_rows[0].mapping_status == "matched"
