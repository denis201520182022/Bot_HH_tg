import datetime
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Text,
    ForeignKey,
    DateTime,
    Date,
    JSON
)
from sqlalchemy.orm import sessionmaker, relationship, declarative_base
from sqlalchemy.dialects.postgresql import JSONB

# Строка подключения к вашей БД из .env файла
DATABASE_URL = "postgresql+psycopg2://user_hr_bot:123@localhost:5432/hr_bot_db?client_encoding=utf8"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class Vacancy(Base):
    __tablename__ = 'vacancies'
    id = Column(Integer, primary_key=True)
    hh_vacancy_id = Column(String(50), unique=True)
    title = Column(String(255), nullable=False)
    city = Column(String(100))
    # Связь для статистики
    statistics = relationship("Statistic", back_populates="vacancy")
    dialogues = relationship("Dialogue", back_populates="vacancy")

class Candidate(Base):
    __tablename__ = 'candidates'
    id = Column(Integer, primary_key=True)
    hh_resume_id = Column(String(50), unique=True)
    full_name = Column(String(255))
    age = Column(Integer)
    citizenship = Column(String(100))
    phone_number = Column(String(50), nullable=True) # nullable=True,
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    dialogues = relationship("Dialogue", back_populates="candidate")

class Dialogue(Base):
    """
    Представляет уникальный диалог по конкретному отклику кандидата на вакансию.
    Это центральная таблица, связывающая кандидатов и вакансии.
    """
    __tablename__ = 'dialogues'
    
    id = Column(Integer, primary_key=True, index=True)
    
    # --- Ключевые идентификаторы ---
    # ID отклика на hh.ru (в их терминологии - negotiation_id). Должен быть уникальным.
    hh_response_id = Column(String(50), unique=True, nullable=False)
    
    # --- Связи с другими таблицами ---
    candidate_id = Column(Integer, ForeignKey('candidates.id'))
    vacancy_id = Column(Integer, ForeignKey('vacancies.id'))
    
    # --- Управление диалогом (FSM - Конечный автомат) ---
    # Текущее состояние диалога, например, 'awaiting_age', 'scheduling_spb_time'.
    dialogue_state = Column(String(100))
    
    # --- Статус этого конкретного отклика ---
    # 'new', 'qualified', 'rejected', 'interview_scheduled_spb', etc.
    # Перенесено из Candidate, так как статус принадлежит отклику, а не кандидату в целом.
    status = Column(String(50), nullable=False, default='new')

     # --- НОВОЕ ПОЛЕ ---
    # Уровень отправленных напоминаний:
    # 0 - не отправлено
    # 1 - отправлено напоминание через 30 мин
    # 2 - отправлено напоминание через 2 часа
    # 3 - отправлено напоминание через 24 часа
    # 4 - диалог "протух" и закрыт
    reminder_level = Column(Integer, nullable=False, default=0, server_default='0')
    
    # --- Хранилище данных ---
    # Полная история переписки в формате JSON.
    # Пример: [{'role': 'user', 'content': '...'}, {'role': 'assistant', 'content': '...'}]
    history = Column(JSONB) # Для PostgreSQL используем JSONB

    # --- Механизм отложенных ответов (Debouncing) ---
    # Временное хранилище для сообщений, которые пришли от пользователя,
    # но на которые бот еще не ответил, ожидая, пока пользователь закончит мысль.
    # Очищается (ставится в NULL) после отправки ответа.
    pending_messages = Column(JSONB)
    
    # --- Временные метки ---
    # Время последнего обновления записи. Используется для определения "зависших" диалогов.
    # Индекс (index=True) ускоряет поиск по этому полю.
    last_updated = Column(DateTime, default=datetime.datetime.utcnow, 
                          onupdate=datetime.datetime.utcnow, index=True) 

    # --- "Навигация" SQLAlchemy ---
    # Позволяет легко получать доступ к связанным объектам: dialogue.candidate, dialogue.vacancy
    candidate = relationship("Candidate", back_populates="dialogues")
    vacancy = relationship("Vacancy", back_populates="dialogues")

class Statistic(Base):
    __tablename__ = 'statistics'
    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    responses_count = Column(Integer, default=0)
    started_dialogs_count = Column(Integer, default=0)
    qualified_count = Column(Integer, default=0)
    
    vacancy_id = Column(Integer, ForeignKey('vacancies.id'))
    vacancy = relationship("Vacancy", back_populates="statistics")


# Команда для создания всех таблиц, если они не существуют
# Base.metadata.create_all(bind=engine)

# models.py
class TelegramUser(Base):
    __tablename__ = 'telegram_users'
    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(String(50), unique=True, nullable=False)
    username = Column(String(100))
    role = Column(String(50), nullable=False, default='user') # 'user' или 'admin'
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # models.py

class NotificationQueue(Base):
    __tablename__ = 'notification_queue'
    id = Column(Integer, primary_key=True, index=True)
    candidate_id = Column(Integer, ForeignKey('candidates.id'), nullable=False)
    status = Column(String(50), nullable=False, default='pending') # pending, sent, error
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    processed_at = Column(DateTime)
    
    candidate = relationship("Candidate")

class TrackedVacancy(Base):
    #Список ID вакансий, отклики на которые нужно обрабатывать."""
    __tablename__ = 'tracked_vacancies'
    id = Column(Integer, primary_key=True, index=True)
    # ID вакансии на hh.ru
    vacancy_id = Column(String(50), unique=True, nullable=False)
    # Название (для удобства админов)
    title = Column(String(255)) 

class TrackedRecruiter(Base):
    #"""Список ID рекрутеров, отклики которых нужно обрабатывать."""
    __tablename__ = 'tracked_recruiters'
    id = Column(Integer, primary_key=True, index=True)
    # ID пользователя (рекрутера) на hh.ru
    recruiter_id = Column(String(50), unique=True, nullable=False)
    # Имя (для удобства админов)
    name = Column(String(100))