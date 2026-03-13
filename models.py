from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Table, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime, timezone

Base = declarative_base()

recipe_tags = Table(
    'recipe_tags',
    Base.metadata,
    Column('recipe_id', Integer, ForeignKey('recipes.id', ondelete='CASCADE')),
    Column('tag_id', Integer, ForeignKey('tags.id', ondelete='CASCADE'))
)


class Recipe(Base):
    __tablename__ = "recipes"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), index=True, nullable=False)
    ingredients = Column(JSON, nullable=False, default=list)  # liste de dicts
    steps = Column(JSON, nullable=False, default=list)         # liste de strings
    servings = Column(Integer, default=4)
    prep_time = Column(Integer, nullable=True)                 # en minutes (int, pas string)
    source_url = Column(String(500), unique=True, index=True, nullable=True)
    image_url = Column(Text, nullable=True)                    # peut être long (base64)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    tags = relationship("Tag", secondary=recipe_tags, back_populates="recipes", lazy="selectin")


class Tag(Base):
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, index=True, nullable=False)

    recipes = relationship("Recipe", secondary=recipe_tags, back_populates="tags")
