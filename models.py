# models.py
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Table
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()

recipe_tags = Table(
    'recipe_tags',
    Base.metadata,
    Column('recipe_id', Integer, ForeignKey('recipes.id')),
    Column('tag_id', Integer, ForeignKey('tags.id'))
)

class Recipe(Base):
    __tablename__ = "recipes"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    ingredients = Column(Text)  # JSON string
    steps = Column(Text)        # JSON string
    servings = Column(Integer, default=4)
    prep_time = Column(String)
    source_url = Column(String, unique=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    image_url = Column(String, nullable=True)
    
    tags = relationship("Tag", secondary=recipe_tags, back_populates="recipes")

class Tag(Base):
    __tablename__ = "tags"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    
    recipes = relationship("Recipe", secondary=recipe_tags, back_populates="tags")
