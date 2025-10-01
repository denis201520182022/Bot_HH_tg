# hr_bot/db/models.py

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
    func
)
from sqlalchemy.dialects.postgresql import JSONB 
from sqlalchemy.orm import sessionmaker, relationship, declarative_base
from sqlalchemy import Numeric, Boolean

DATABASE_URL = "postgresql+psycopg2://user_hr_bot:123@localhost:5432/hr_bot_db?client_encoding=utf8"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Vacancy(Base):
    __tablename__ = 'vacancies'
    id = Column(Integer, primary_key=True, index=True)
    hh_vacancy_id = Column(String(50), unique=True)
    title = Column(String(255), nullable=False)
    city = Column(String(100))
    statistics = relationship("Statistic", back_populates="vacancy")
    dialogues = relationship("Dialogue", back_populates="vacancy")

class Candidate(Base):
    __tablename__ = 'candidates'
    id = Column(Integer, primary_key=True, index=True)
    hh_resume_id = Column(String(50), unique=True)
    full_name = Column(String(255))
    age = Column(Integer)
    citizenship = Column(String(100))
    phone_number = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    city = Column(String(255), nullable=True) # Поле с прошлого шага
    
    # --- ДОБАВЬТЕ ЭТУ СТРОКУ ---
    readiness_to_start = Column(String(255), nullable=True)
    dialogues = relationship("Dialogue", back_populates="candidate")

class TrackedRecruiter(Base):
    __tablename__ = 'tracked_recruiters'
    id = Column(Integer, primary_key=True, index=True)
    recruiter_id = Column(String(50), unique=True, nullable=False)
    name = Column(String(100))
    refresh_token = Column(Text, nullable=True)
    access_token = Column(Text, nullable=True)
    token_expires_at = Column(DateTime(timezone=True), nullable=True)
    dialogues = relationship("Dialogue", back_populates="recruiter")

class Dialogue(Base):
    __tablename__ = 'dialogues'
    id = Column(Integer, primary_key=True, index=True)
    hh_response_id = Column(String(50), unique=True, nullable=False)
    recruiter_id = Column(Integer, ForeignKey('tracked_recruiters.id'))
    candidate_id = Column(Integer, ForeignKey('candidates.id'))
    vacancy_id = Column(Integer, ForeignKey('vacancies.id'))
    dialogue_state = Column(String(100))
    status = Column(String(50), nullable=False, default='new')
    reminder_level = Column(Integer, nullable=False, default=0, server_default='0')
    history = Column(JSONB)
    pending_messages = Column(JSONB)
    last_updated = Column(
        DateTime(timezone=True), 
        server_default=func.now(),
        onupdate=func.now(),
        index=True
    )
    candidate = relationship("Candidate", back_populates="dialogues")
    vacancy = relationship("Vacancy", back_populates="dialogues")
    recruiter = relationship("TrackedRecruiter", back_populates="dialogues")

class Statistic(Base):
    __tablename__ = 'statistics'
    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, default=datetime.date.today)
    responses_count = Column(Integer, default=0)
    started_dialogs_count = Column(Integer, default=0)
    qualified_count = Column(Integer, default=0)
    vacancy_id = Column(Integer, ForeignKey('vacancies.id'))
    vacancy = relationship("Vacancy", back_populates="statistics")

class TelegramUser(Base):
    __tablename__ = 'telegram_users'
    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(String(50), unique=True, nullable=False)
    username = Column(String(100))
    role = Column(String(50), nullable=False, default='user')
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class NotificationQueue(Base):
    __tablename__ = 'notification_queue'
    id = Column(Integer, primary_key=True, index=True)
    candidate_id = Column(Integer, ForeignKey('candidates.id'), nullable=False)
    status = Column(String(50), nullable=False, default='pending')
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    processed_at = Column(DateTime(timezone=True))
    candidate = relationship("Candidate")

class TrackedVacancy(Base):
    __tablename__ = 'tracked_vacancies'
    id = Column(Integer, primary_key=True, index=True)
    vacancy_id = Column(String(50), unique=True, nullable=False)
    title = Column(String(255))


class AppSettings(Base):
    """Глобальные настройки приложения (лимиты, тарифы)."""
    __tablename__ = 'app_settings'
    
    id = Column(Integer, primary_key=True)
    # Общее количество разрешенных откликов
    limit_total = Column(Integer, nullable=False, default=50)
    # Количество уже использованных откликов
    limit_used = Column(Integer, nullable=False, default=0)
    # Стоимость одного отклика (используем Numeric для точности)
    cost_per_response = Column(Numeric(10, 2), nullable=False, default=100.00)
    # Флаг, который показывает, было ли уже отправлено уведомление о низком лимите
    low_limit_notified = Column(Boolean, nullable=False, default=False)