from dataclasses import dataclass

from app.services.employee_matching import (
    build_employee_name_index,
    normalize_person_name,
)


@dataclass
class EmployeeLike:
    full_name: str
    personnel_number: str


def test_normalized_name_is_the_identity_key_not_personnel_number():
    first_position = EmployeeLike("Смирнова Марина Викторовна", "00125")
    second_position = EmployeeLike("Смирнова Марина Викторовна", "00987")
    another_employee = EmployeeLike("Виноградова Наталья Михайловна", "00126")

    index = build_employee_name_index(
        [first_position, second_position, another_employee]
    )

    assert index[normalize_person_name("Смирнова Марина Викторовна")] is first_position
    assert index[normalize_person_name("Виноградова Наталья Михайловна")] is another_employee
    assert len(index) == 2


def test_name_normalization_ignores_case_punctuation_spaces_and_yo():
    assert normalize_person_name("  СМИРНОВА   Марина Викторовна ") == normalize_person_name(
        "Смирнова, Марина Викторовна"
    )
    assert normalize_person_name("Семёнов") == normalize_person_name("Семенов")


def test_employment_annotations_do_not_change_employee_identity():
    base = "Смирнова Марина Викторовна"
    assert normalize_person_name(base) == normalize_person_name(
        "Смирнова Марина Викторовна (внутр.совм.)"
    )
    assert normalize_person_name(base) == normalize_person_name(
        "Смирнова Марина Викторовна (внешн.совм.)"
    )
    assert normalize_person_name(base) == normalize_person_name(
        "Смирнова Марина Викторовна (внутреннее совместительство)"
    )


def test_fio_variants_resolve_to_one_employee_despite_different_position_numbers():
    employee = EmployeeLike("Смирнова Марина Викторовна", "00125")
    index = build_employee_name_index([employee])

    first_row = normalize_person_name("Смирнова Марина Викторовна")
    second_row = normalize_person_name("СМИРНОВА, Марина Викторовна")

    assert index[first_row] is employee
    assert index[second_row] is employee
