import uuid
from datetime import date, datetime
from sqlalchemy import Boolean, CheckConstraint, Computed, Date, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

uid = lambda: uuid.uuid4()

class Organization(Base):
    __tablename__ = 'organizations'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    short_name: Mapped[str | None] = mapped_column(String(100))
    inn: Mapped[str | None] = mapped_column(String(12), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class User(Base):
    __tablename__ = 'users'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uid)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (CheckConstraint("role IN ('central_hr','responsible')", name='ck_users_role'),)

class UserOrganization(Base):
    __tablename__ = 'user_organizations'
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('organizations.id', ondelete='CASCADE'), primary_key=True)

class Employee(Base):
    __tablename__ = 'employees'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uid)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('organizations.id', ondelete='RESTRICT'), nullable=False)
    personnel_number: Mapped[str | None] = mapped_column(String(50))
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint('id','organization_id',name='uq_employees_id_org'), Index('uq_employee_org_personnel_number','organization_id','personnel_number',unique=True,postgresql_where=personnel_number.is_not(None)))

class Campaign(Base):
    __tablename__ = 'campaigns'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uid)
    year: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default='draft', nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='SET NULL'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint('year BETWEEN 2000 AND 2200', name='ck_campaign_year'), CheckConstraint("status IN ('draft','open','closed','archived')", name='ck_campaign_status'))

class CampaignOrganization(Base):
    __tablename__ = 'campaign_organizations'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uid)
    campaign_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('campaigns.id', ondelete='RESTRICT'), nullable=False)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('organizations.id', ondelete='RESTRICT'), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default='pending', nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint('campaign_id','organization_id',name='uq_campaign_organization'), UniqueConstraint('id','organization_id',name='uq_campaign_org_id_org'), CheckConstraint("status IN ('pending','imported','in_progress','completed')", name='ck_campaign_org_status'))

class TemplateFile(Base):
    __tablename__ = 'template_files'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uid)
    campaign_organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='SET NULL'))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (ForeignKeyConstraint(['campaign_organization_id','organization_id'],['campaign_organizations.id','campaign_organizations.organization_id'],name='fk_template_campaign_org'), UniqueConstraint('campaign_organization_id','version_number',name='uq_template_version'), CheckConstraint('version_number >= 1',name='ck_template_version'))

class TemplateRow(Base):
    __tablename__ = 'template_rows'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uid)
    template_file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('template_files.id', ondelete='CASCADE'), nullable=False)
    employee_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey('employees.id', ondelete='RESTRICT'))
    sheet_name: Mapped[str] = mapped_column(String(100), nullable=False)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    department_name: Mapped[str | None] = mapped_column(String(255))
    position_name: Mapped[str | None] = mapped_column(String(255))
    employee_name: Mapped[str | None] = mapped_column(String(255))
    personnel_number: Mapped[str | None] = mapped_column(String(50))
    mapping_status: Mapped[str] = mapped_column(String(30), default='unmatched', nullable=False)
    __table_args__ = (UniqueConstraint('template_file_id','sheet_name','row_number',name='uq_template_row_location'), CheckConstraint('row_number > 0',name='ck_template_row_number'), CheckConstraint("mapping_status IN ('unmatched','matched','needs_review','ignored')",name='ck_template_mapping_status'))

class VacationPlan(Base):
    __tablename__ = 'vacation_plans'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uid)
    campaign_organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='SET NULL'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (ForeignKeyConstraint(['campaign_organization_id','organization_id'],['campaign_organizations.id','campaign_organizations.organization_id'],name='fk_plan_campaign_org'), ForeignKeyConstraint(['employee_id','organization_id'],['employees.id','employees.organization_id'],name='fk_plan_employee_org'), UniqueConstraint('campaign_organization_id','employee_id',name='uq_plan_employee_campaign'))

class VacationPeriod(Base):
    __tablename__ = 'vacation_periods'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uid)
    vacation_plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('vacation_plans.id',ondelete='CASCADE'), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    duration_days: Mapped[int] = mapped_column(Integer, Computed('end_date - start_date + 1',persisted=True))
    sort_order: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    __table_args__ = (CheckConstraint('end_date >= start_date',name='ck_period_dates'), CheckConstraint('sort_order > 0',name='ck_period_sort_order'))

class ExportFile(Base):
    __tablename__ = 'export_files'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uid)
    campaign_organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('campaign_organizations.id',ondelete='RESTRICT'), nullable=False)
    template_file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('template_files.id',ondelete='RESTRICT'), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey('users.id',ondelete='SET NULL'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class AuditLog(Base):
    __tablename__ = 'audit_log'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uid)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey('users.id',ondelete='SET NULL'))
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    details: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
