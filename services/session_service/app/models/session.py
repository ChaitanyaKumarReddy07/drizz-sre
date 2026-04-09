from sqlalchemy import Column, String, DateTime, Enum as SAEnum, Integer, JSON, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db import Base
import enum, uuid

class SessionHealth(str, enum.Enum):
    ALIVE = "alive"
    EXPIRED = "expired"
    UNKNOWN = "unknown"

class SessionTier(str, enum.Enum):
    HOT = "hot"
    WARM = "warm"
    COLD = "cold"

class LoginMethod(str, enum.Enum):
    OTP = "otp"
    SSO = "sso"
    PASSWORD = "password"
    BIOMETRIC = "biometric"

class AppSession(Base):
    __tablename__ = "app_sessions"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    app_id = Column(String, nullable=False)
    snapshot_id = Column(String, nullable=True)
    health = Column(SAEnum(SessionHealth), default=SessionHealth.UNKNOWN)
    tier = Column(SAEnum(SessionTier), default=SessionTier.WARM)
    login_method = Column(SAEnum(LoginMethod), default=LoginMethod.PASSWORD)
    use_count = Column(Integer, default=0)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    last_verified_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    health_events = relationship("SessionHealthEvent", back_populates="session", cascade="all, delete-orphan")

class SessionHealthEvent(Base):
    __tablename__ = "session_health_events"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String, ForeignKey("app_sessions.id"), nullable=False, index=True)
    health = Column(SAEnum(SessionHealth), nullable=False)
    checked_at = Column(DateTime(timezone=True), server_default=func.now())
    detail = Column(JSON, default=dict)
    session = relationship("AppSession", back_populates="health_events")
