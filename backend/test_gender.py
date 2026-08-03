"""Тесты эвристики определения пола по ФИО."""
import pytest

from backend.gender import detect_gender

FEMALE = [
    "Иванова Мария Петровна",
    "Петрова Ольга",
    "Каримова Дилноза Рустамовна",
    "Юлдашева Нигора",
    "Ким Любовь Сергеевна",
    "Абдуллаева Гулбахор Акрамовна",
    "Рахимова Зухра",
    "Соколова Анна Ильинична",
    "Турсунова Малика Бахтиёр кизи",
    "Смирнова Екатерина Александровна",
]

MALE = [
    "Иванов Иван Петрович",
    "Каримов Алишер Рустамович",
    "Юлдашев Бекзод",
    "Соколов Никита Ильич",       # мужское имя на -а
    "Ахмедов Жасур Улугбек угли",
    "Ким Данила Сергеевич",
    "Петров Илья",
    "Тошматов Отабек Аброрович",
    "Сидоров Кузьма",
    "Мирзаев Санжар Фарходович",
]


@pytest.mark.parametrize("name", FEMALE)
def test_female(name):
    assert detect_gender(name) == "f", name


@pytest.mark.parametrize("name", MALE)
def test_male(name):
    assert detect_gender(name) == "m", name


def test_patronymic_wins_over_surname():
    # Фамилия без окончания, решает отчество.
    assert detect_gender("Ким Ольга Сергеевна") == "f"
    assert detect_gender("Ким Сергей Олегович") == "m"


def test_unknown():
    assert detect_gender("") is None
    assert detect_gender(None) is None
    assert detect_gender("Ц") is None


def test_case_and_yo_insensitive():
    assert detect_gender("КОРОЛЁВА ЖАННА") == "f"
    assert detect_gender("королёв пётр") == "m"
