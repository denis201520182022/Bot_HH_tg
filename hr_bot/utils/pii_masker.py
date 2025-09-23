# hr_bot/utils/pii_masker.py

import re
from typing import Tuple, Optional

# --- ОБНОВЛЕННЫЕ РЕГУЛЯРНЫЕ ВЫРАЖЕНИЯ ---
# Для ФИО: ищем 2 или 3 слова подряд, где каждое начинается с заглавной буквы
FIO_PATTERN = re.compile(
    r'\b([А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?)\s+([А-ЯЁ][а-яё]+)\s+(([А-ЯЁ][а-яё]+))?\b'
)

# Для телефона: более точное, ищет 10-11 цифр с возможными префиксами и разделителями
PHONE_PATTERN = re.compile(
    r'(?:\+7|8)?[ \-.(]*(\d{3})[ \-.)]*(\d{3})[ \-.]*(\d{2})[ \-.]*(\d{2})\b'
)

# --- НОВЫЕ ФУНКЦИИ МАСКИРОВКИ ---
def _mask_fio_match(match: re.Match) -> str:
    """Маскирует Имя и Отчество, оставляя Фамилию."""
    surname = match.group(1)
    name = match.group(2)
    patronymic = match.group(3)

    masked_name = f"{name[0]}***"
    
    if patronymic:
        masked_patronymic = f"{patronymic[0]}***"
        return f"{surname} {masked_name} {masked_patronymic}"
    return f"{surname} {masked_name}"

def _mask_phone_number(phone: str) -> str:
    """Маскирует номер телефона. Пример: +7(999)123-45-67 -> +7(999)***-**-67"""
    # Убираем все не-цифры
    digits = re.sub(r'\D', '', phone)
    if len(digits) > 10: # +7... или 8...
        return f"+7({digits[1:4]})***-**-{digits[-2:]}"
    else: # 10 цифр без кода страны
        return f"+7({digits[0:3]})***-**-{digits[-2:]}"

# --- ГЛАВНАЯ ФУНКЦИЯ ---
def extract_and_mask_pii(text: str) -> Tuple[str, Optional[str], Optional[str]]:
    """
    Извлекает ФИО и номер телефона, а затем маскирует их в тексте.
    Возвращает: (замаскированный_текст, извлеченное_фио, извлеченный_телефон)
    """
    if not text:
        return "", None, None

    extracted_fio = None
    extracted_phone = None
    
    # --- Извлечение и маскировка телефона ---
    phone_match = PHONE_PATTERN.search(text)
    if phone_match:
        # Собираем полный номер из групп
        full_phone = ''.join(phone_match.groups())
        if len(full_phone) == 10:
            extracted_phone = '7' + full_phone # Нормализуем до формата 7...
        
        # Маскируем номер в тексте
        masked_text = PHONE_PATTERN.sub(_mask_phone_number(full_phone), text, count=1)
    else:
        masked_text = text

    # --- Извлечение и маскировка ФИО ---
    fio_match = FIO_PATTERN.search(masked_text) # Ищем в уже частично замаскированном тексте
    if fio_match:
        extracted_fio = fio_match.group(0)
        masked_text = FIO_PATTERN.sub(_mask_fio_match, masked_text, count=1)

    return masked_text, extracted_fio, extracted_phone

# --- Тесты для проверки ---
if __name__ == '__main__':
    test_case = "Мои данные: Иванов Иван Иванович, мой телефон +7 (999) 123-45-67. Прошу связаться."
    masked, fio, phone = extract_and_mask_pii(test_case)
    print(f"Оригинал: {test_case}")
    print(f"  Маска: {masked}")
    print(f"  Извлечено ФИО: {fio}")
    print(f"  Извлечен Телефон: {phone}")