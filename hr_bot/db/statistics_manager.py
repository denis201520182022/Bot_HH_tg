from datetime import date
from sqlalchemy.orm import Session
from .models import Statistic

def update_stats(db: Session, vacancy_id: int, responses: int = 0, started_dialogs: int = 0, qualified: int = 0):
    """
    Находит или создает запись о статистике за сегодняшний день для вакансии
    и инкрементирует нужные счетчики.
    """
    today = date.today()

    # Ищем запись статистики для этой вакансии за сегодня
    stats_record = db.query(Statistic).filter(
        Statistic.vacancy_id == vacancy_id,
        Statistic.date == today
    ).first()

    # Если записи нет, создаем ее
    if not stats_record:
        stats_record = Statistic(
            vacancy_id=vacancy_id,
            date=today
        )
        db.add(stats_record)
        # Нужно сделать flush, чтобы получить ID, если это новая запись
        db.flush() 

    # Инкрементируем счетчики
    stats_record.responses_count += responses
    stats_record.started_dialogs_count += started_dialogs
    stats_record.qualified_count += qualified

    db.commit()
    print(f"  > Статистика для вакансии {vacancy_id} обновлена: +{responses} откликов, +{started_dialogs} диалогов, +{qualified} квалифицировано.")