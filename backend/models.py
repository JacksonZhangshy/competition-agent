"""数据模型：竞赛台账 + 业务单据 + 知识库 + 智能体会话。

设计原则（对应需求"避免知识和规则固化在代码中"）：
- 赛项规则、材料清单、评分权重、单据模板一律入库（SystemConfig / Edition.rules_json）
- 结构化统计只依赖本文件的业务表，不依赖大模型生成
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def now() -> dt.datetime:
    return dt.datetime.now()


# ---------------------------------------------------------------- 基础主体
class Student(Base):
    __tablename__ = "student"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sno: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64))
    gender: Mapped[str] = mapped_column(String(8), default="男")
    college: Mapped[str] = mapped_column(String(64), default="", index=True, comment="所属学院")
    major: Mapped[str] = mapped_column(String(64), index=True)
    grade: Mapped[int] = mapped_column(Integer, index=True, comment="入学年份")
    class_name: Mapped[str] = mapped_column(String(64), default="")
    phone: Mapped[str] = mapped_column(String(32), default="")
    email: Mapped[str] = mapped_column(String(128), default="")

    @property
    def grade_label(self) -> str:
        """当前年级，如 2026 年时 2023 级学生为大四。"""
        current = dt.date.today().year
        delta = current - self.grade + 1
        names = {1: "大一", 2: "大二", 3: "大三", 4: "大四", 5: "大五"}
        return names.get(delta, f"{self.grade}级")


class Teacher(Base):
    __tablename__ = "teacher"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tno: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(32), default="讲师")
    dept: Mapped[str] = mapped_column(String(64), default="")
    phone: Mapped[str] = mapped_column(String(32), default="")
    email: Mapped[str] = mapped_column(String(128), default="")


# ---------------------------------------------------------------- 赛事
class Competition(Base):
    """赛事本体（跨年度稳定信息）。"""

    __tablename__ = "competition"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    short_name: Mapped[str] = mapped_column(String(64), default="")
    level: Mapped[str] = mapped_column(String(32), index=True, comment="国家级/省级/校级/行业级")
    category: Mapped[str] = mapped_column(String(32), index=True, comment="学科竞赛/创新创业/程序设计/数学建模/电子设计/外语")
    organizer: Mapped[str] = mapped_column(String(200), default="")
    official_url: Mapped[str] = mapped_column(String(300), default="")
    majors: Mapped[str] = mapped_column(String(300), default="", comment="适配专业，逗号分隔，空表示不限")
    grades: Mapped[str] = mapped_column(String(64), default="", comment="适配年级，如 2,3,4")
    difficulty: Mapped[int] = mapped_column(Integer, default=3, comment="1-5 难度")
    workload: Mapped[int] = mapped_column(Integer, default=3, comment="1-5 备赛投入")
    description: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[str] = mapped_column(String(300), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    editions: Mapped[list["Edition"]] = relationship(back_populates="competition", cascade="all, delete-orphan")


class Edition(Base):
    """赛事届次 / 年度。统计与推荐按此维度聚合。"""

    __tablename__ = "edition"
    __table_args__ = (UniqueConstraint("competition_id", "year", name="uq_edition_comp_year"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    competition_id: Mapped[int] = mapped_column(ForeignKey("competition.id", ondelete="CASCADE"), index=True)
    year: Mapped[int] = mapped_column(Integer, index=True)
    seq: Mapped[int] = mapped_column(Integer, default=1, comment="第几届")
    notice_title: Mapped[str] = mapped_column(String(300), default="")
    signup_start: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    signup_end: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    contest_start: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    contest_end: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    fee: Mapped[float] = mapped_column(Float, default=0.0, comment="报名费（元/队）")
    venue: Mapped[str] = mapped_column(String(128), default="")
    status: Mapped[str] = mapped_column(String(16), default="未开始")
    rules_json: Mapped[dict] = mapped_column(JSON, default=dict, comment="报名条件/材料/奖项/流程等规则")

    competition: Mapped["Competition"] = relationship(back_populates="editions")
    teams: Mapped[list["Team"]] = relationship(back_populates="edition")


class Team(Base):
    """参赛项目：统计的最小颗粒度。"""

    __tablename__ = "team"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    edition_id: Mapped[int] = mapped_column(ForeignKey("edition.id", ondelete="CASCADE"), index=True)
    project_name: Mapped[str] = mapped_column(String(300))
    leader_student_id: Mapped[int | None] = mapped_column(ForeignKey("student.id"), nullable=True, index=True)
    teacher_id: Mapped[int | None] = mapped_column(ForeignKey("teacher.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="报名", index=True)
    award_level: Mapped[str] = mapped_column(String(16), default="无", index=True, comment="特等奖/一等奖/二等奖/三等奖/优秀奖/无")
    award_grade: Mapped[str] = mapped_column(String(16), default="无", index=True, comment="国家级/省级/校级/无")
    signup_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    finish_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    budget_total: Mapped[float] = mapped_column(Float, default=0.0)
    remark: Mapped[str] = mapped_column(Text, default="")

    edition: Mapped["Edition"] = relationship(back_populates="teams")
    leader: Mapped["Student"] = relationship(foreign_keys=[leader_student_id])
    teacher: Mapped["Teacher"] = relationship(foreign_keys=[teacher_id])
    members: Mapped[list["TeamMember"]] = relationship(back_populates="team", cascade="all, delete-orphan")


class TeamMember(Base):
    __tablename__ = "team_member"
    __table_args__ = (UniqueConstraint("team_id", "student_id", name="uq_team_member"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("team.id", ondelete="CASCADE"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("student.id"), index=True)
    role: Mapped[str] = mapped_column(String(16), default="成员")

    team: Mapped["Team"] = relationship(back_populates="members")
    student: Mapped["Student"] = relationship()


# ---------------------------------------------------------------- 经费业务
class BudgetRequest(Base):
    __tablename__ = "budget_request"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    budget_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("team.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    items: Mapped[list] = mapped_column(JSON, default=list, comment="[{name, spec, unit, qty, price, amount, note}]")
    total: Mapped[float] = mapped_column(Float, default=0.0)
    approved_amount: Mapped[float] = mapped_column(Float, default=0.0)
    applicant: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(16), default="草稿", index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class LoanRequest(Base):
    __tablename__ = "loan_request"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    loan_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    budget_id: Mapped[int | None] = mapped_column(ForeignKey("budget_request.id"), nullable=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("team.id"), nullable=True, index=True)
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    borrower: Mapped[str] = mapped_column(String(64), default="")
    payee: Mapped[str] = mapped_column(String(128), default="")
    bank_account: Mapped[str] = mapped_column(String(64), default="")
    purpose: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(16), default="草稿", index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class Reimbursement(Base):
    __tablename__ = "reimbursement"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reimb_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("team.id"), nullable=True, index=True)
    budget_id: Mapped[int | None] = mapped_column(ForeignKey("budget_request.id"), nullable=True)
    items: Mapped[list] = mapped_column(JSON, default=list, comment="[{name, amount, invoice_no, invoice_date, invoice_type}]")
    total: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16), default="草稿", index=True)
    check_result: Mapped[dict] = mapped_column(JSON, default=dict, comment="材料完整性检查结果")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


# ---------------------------------------------------------------- 知识库
class KnowledgeDoc(Base):
    __tablename__ = "knowledge_doc"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    filename: Mapped[str] = mapped_column(String(300))
    filetype: Mapped[str] = mapped_column(String(16), default="txt")
    category: Mapped[str] = mapped_column(String(32), default="政策", index=True, comment="政策/规程/通知/模板/其他")
    year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    source_path: Mapped[str] = mapped_column(String(500), default="")
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="已入库")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)

    chunks: Mapped[list["KnowledgeChunk"]] = relationship(back_populates="doc", cascade="all, delete-orphan")


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunk"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    doc_id: Mapped[int] = mapped_column(ForeignKey("knowledge_doc.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text)
    heading: Mapped[str] = mapped_column(String(300), default="")
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    vector: Mapped[list | None] = mapped_column(JSON, nullable=True)
    tokens: Mapped[str] = mapped_column(Text, default="", comment="检索用分词结果，空格分隔")

    doc: Mapped["KnowledgeDoc"] = relationship(back_populates="chunks")


# ---------------------------------------------------------------- 会话与运行
class Conversation(Base):
    __tablename__ = "conversation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), default="新对话")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now, onupdate=now)

    messages: Mapped[list["Message"]] = relationship(back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "message"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversation.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    citations: Mapped[list] = mapped_column(JSON, default=list)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


class AgentRun(Base):
    """每次智能体执行的轨迹，用于工作流说明与测试报告。"""

    __tablename__ = "agent_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workflow: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16), default="success")
    input_data: Mapped[dict] = mapped_column(JSON, default=dict)
    output_data: Mapped[dict] = mapped_column(JSON, default=dict)
    trace: Mapped[list] = mapped_column(JSON, default=list, comment="节点级执行轨迹")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now, index=True)


class SystemConfig(Base):
    """键值配置：赛项规则、单据模板、评分权重等，改这里不用改代码。"""

    __tablename__ = "system_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    remark: Mapped[str] = mapped_column(String(300), default="")
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now, onupdate=now)
