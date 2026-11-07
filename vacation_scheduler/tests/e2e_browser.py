"""Real Chromium smoke test for the central HR and organization representative flows.

Run after migrations with the app served at BASE_URL.
"""
import os
import re
import time
from io import BytesIO
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen
from uuid import uuid4

from openpyxl import load_workbook
from playwright.sync_api import sync_playwright
from sqlalchemy import select

from app.database import SessionLocal
from app.excel.importer import parse_workbook
from app.main import normalize_person_name
from app.models.entities import Employee, Organization, User
from app.security import hash_password


BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000")
PASSWORD = "Browser-E2E-Password-2026!"


def wait_for_app():
    for _ in range(60):
        try:
            with urlopen(f"{BASE_URL}/health", timeout=2) as response:
                if response.status == 200:
                    return
        except (URLError, TimeoutError, OSError):
            time.sleep(1)
    raise RuntimeError("Application did not become healthy within 60 seconds")


def seed_data():
    suffix = uuid4().hex[:8]
    workbook_path = Path(__file__).resolve().parents[2] / "ГРАФИК ОТПУСКОВ ООО  2026.xlsx"
    parsed_rows = parse_workbook(workbook_path)
    names = {}
    for row in parsed_rows:
        normalized = normalize_person_name(row["employee_name"])
        if normalized and normalized not in names:
            names[normalized] = row["employee_name"]

    with SessionLocal() as db:
        hr = User(
            username=f"browser-hr-{suffix}",
            full_name="Browser Test Central HR",
            password_hash=hash_password(PASSWORD),
            role="central_hr",
            is_active=True,
        )
        denied = Organization(name=f"Browser Restricted {suffix}")
        db.add_all([hr, denied])
        db.flush()
        db.commit()
        return {
            "hr_username": hr.username,
            "allowed_name": f"Browser Allowed {suffix}",
            "denied_name": denied.name,
            "workbook_path": str(workbook_path),
            "first_employee_name": next(iter(names.values())),
            "first_row": next(
                row for row in parsed_rows if normalize_person_name(row["employee_name"])
            ),
        }


def names_from_workbook(workbook_path):
    names = {}
    for row in parse_workbook(workbook_path):
        normalized = normalize_person_name(row["employee_name"])
        if normalized and normalized not in names:
            names[normalized] = row["employee_name"]
    return list(names.values())


def main():
    wait_for_app()
    data = seed_data()
    suffix = data["allowed_name"].split()[-1]
    responsible_username = f"browser-user-{suffix}"
    campaign_name = f"Browser E2E campaign {suffix}"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(accept_downloads=True)

        # Central HR signs in and creates a responsible account for the organization.
        page.goto(f"{BASE_URL}/login")
        page.get_by_label("Имя пользователя").fill(data["hr_username"])
        page.get_by_label("Пароль").fill(PASSWORD)
        page.get_by_role("button", name="Войти").click()
        page.get_by_role("heading", name="Доступные организации").wait_for()
        page.get_by_role("link", name="Пользователи").click()
        page.get_by_label("Полное название").fill(data["allowed_name"])
        page.get_by_role("button", name="Добавить").click()
        page.get_by_text("Организация создана.").wait_for()

        # Seed the workbook's distinct FIOs after the organization was created in the UI.
        with SessionLocal() as db:
            organization = db.scalar(select(Organization).where(Organization.name == data["allowed_name"]))
            for full_name in names_from_workbook(data["workbook_path"]):
                db.add(Employee(organization_id=organization.id, full_name=full_name, is_active=True))
            db.commit()

        page.get_by_label("Логин").fill(responsible_username)
        page.locator("#new-full-name").fill("Browser Test Responsible")
        page.get_by_label("Временный пароль").fill(PASSWORD)
        page.locator("#new-orgs").select_option(label=data["allowed_name"])
        page.get_by_role("button", name="Создать пользователя").click()
        page.get_by_text("Пользователь создан.").wait_for()

        # Central HR creates the campaign for the selected organization.
        page.goto(f"{BASE_URL}/campaigns")
        page.get_by_label("Год").fill("2097")
        page.get_by_label("Название").fill(campaign_name)
        page.locator('select[name="organization_ids"]').select_option(label=data["allowed_name"])
        page.get_by_role("button", name="Создать").click()
        page.get_by_text(campaign_name).wait_for()

        # The responsible user sees only the assigned organization and cannot open HR admin.
        page.goto(f"{BASE_URL}/")
        page.locator('form[action="/logout"] button').click()
        page.get_by_label("Имя пользователя").fill(responsible_username)
        page.get_by_label("Пароль").fill(PASSWORD)
        page.get_by_role("button", name="Войти").click()
        page.get_by_text(data["allowed_name"]).wait_for()
        assert data["denied_name"] not in page.locator("main").inner_text()
        forbidden_response = page.goto(f"{BASE_URL}/admin/users")
        assert forbidden_response is not None and forbidden_response.status == 403

        # Upload the real T-7 template; pre-seeded employee names should auto-match.
        page.goto(f"{BASE_URL}/campaigns")
        page.get_by_text(campaign_name).click()

        # Verify a corrupt workbook produces a visible, recoverable error in the browser.
        invalid_workbook = Path("/tmp") / f"invalid-template-{suffix}.xlsx"
        invalid_workbook.write_bytes(b"this is not an Excel workbook")
        page.locator('input[type="file"][name="file"]').set_input_files(str(invalid_workbook))
        page.get_by_role("button", name="Загрузить и разобрать").click()
        page.wait_for_load_state("networkidle")
        assert "upload_error=" in page.url
        assert page.locator(".alert.alert-danger").count() == 1
        assert "Не удалось загрузить шаблон." in page.locator(".alert.alert-danger").inner_text()
        assert "Файл не удалось прочитать" in page.locator(".alert.alert-danger").inner_text()

        # A failed upload must not block the user from uploading the valid original.
        page.locator('input[type="file"][name="file"]').set_input_files(data["workbook_path"])
        page.get_by_role("button", name="Загрузить и разобрать").click()
        page.wait_for_load_state("networkidle")
        assert page.get_by_role("heading", name="Найденные строки сотрудников").count() == 1, (
            f"Template upload did not render the parsed rows. "
            f"URL={page.url}; body={page.locator('body').inner_text()[:3000]}"
        )
        assert page.get_by_text("Не сопоставлено", exact=True).count() == 0

        page.get_by_role("link", name="Ввод периодов и экспорт Excel").click()
        employee_card = page.locator("section.card").filter(
            has=page.get_by_role("heading", name=data["first_employee_name"], exact=True)
        )
        first_form = employee_card.locator('form[action*="/periods"]')
        first_form.locator('input[name="start_date"]').fill("2027-03-01")
        first_form.locator('input[name="end_date"]').fill("2027-03-14")
        first_form.get_by_role("button", name="Добавить период").click()
        page.get_by_text("14", exact=True).first.wait_for()

        page.get_by_role("button", name="Сформировать Excel по оригинальному шаблону").click()
        download_link = page.locator('a[href^="/exports/"][href$="/download"]').first
        with page.expect_download() as download_info:
            download_link.click()
        download = download_info.value
        output = Path("/tmp") / download.suggested_filename
        download.save_as(output)

        workbook = load_workbook(output, data_only=False)
        sheet = workbook["TDSheet"]
        row = data["first_row"]
        row_number = row["row_number"]
        assert sheet[f"D{row_number}"].value == row["personnel_number"]
        assert sheet[f"E{row_number}"].value == 14
        assert sheet[f"G{row_number}"].value == "01.03.2027 (14)"
        workbook.close()
        browser.close()
        print("Browser E2E passed: central HR, access scoping, T-7 upload, vacation entry and Excel download.")


if __name__ == "__main__":
    main()
