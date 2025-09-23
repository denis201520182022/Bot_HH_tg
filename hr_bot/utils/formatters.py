# hr_bot/utils/formatters.py

def mask_fio(full_name: str | None) -> str:
    """
    Маскирует имя и отчество в полном ФИО.
    Пример: "Иванов Иван Иванович" -> "Иванов И*** И***"
    Пример: "Петрова Анна" -> "Петрова А***"
    """
    if not full_name:
        return "Не указано"

    parts = full_name.strip().split()
    
    if len(parts) == 0:
        return "Не указано"
    
    surname = parts[0]
    
    if len(parts) > 1:
        first_name = parts[1]
        masked_first_name = f"{first_name[0]}***"
    else:
        return surname # Если только фамилия, возвращаем как есть

    if len(parts) > 2:
        patronymic = parts[2]
        masked_patronymic = f"{patronymic[0]}***"
        return f"{surname} {masked_first_name} {masked_patronymic}"
    
    return f"{surname} {masked_first_name}"

