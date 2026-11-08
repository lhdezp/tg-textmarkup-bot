from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tg_textmarkup_bot.db.engine import Base


class Template(Base):
    __tablename__ = "templates"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_templates_owner_name"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    segments: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    photo: Mapped[str | None] = mapped_column(Text, nullable=True)
    inline_buttons: Mapped[list[list[dict[str, Any]]] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
