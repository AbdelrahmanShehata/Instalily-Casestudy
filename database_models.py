from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Text, Date, ForeignKey,
    DateTime, func
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Database setup
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///tedlar_leads.db")
engine = create_engine(DATABASE_URL)
Base = declarative_base()

class Event(Base):
    __tablename__ = 'events'
    event_id       = Column(Integer, primary_key=True)
    name           = Column(String(255), nullable=False)
    event_type     = Column(String(100))
    description    = Column(Text)
    website        = Column(String(255))
    start_date     = Column(Date)
    end_date       = Column(Date)
    location       = Column(String(255))
    relevance_score= Column(Float)
    last_updated   = Column(DateTime, default=func.now())
    notes          = Column(Text)

    associations = relationship("AssociationEvent", back_populates="event")
    companies    = relationship("CompanyEvent",     back_populates="event")

class Association(Base):
    __tablename__ = 'associations'
    association_id = Column(Integer, primary_key=True)
    name           = Column(String(255), nullable=False)
    industry       = Column(String(255))
    description    = Column(Text)
    website        = Column(String(255))
    relevance_score= Column(Float)
    last_updated   = Column(DateTime, default=func.now())
    notes          = Column(Text)

    events = relationship("AssociationEvent", back_populates="association")

class Company(Base):
    __tablename__ = 'companies'
    company_id      = Column(Integer, primary_key=True)
    name            = Column(String(255), nullable=False)
    industry        = Column(String(255))
    description     = Column(Text)
    website         = Column(String(255))
    estimated_revenue = Column(String(100))
    company_size    = Column(String(50))
    relevance_score = Column(Float)
    last_updated    = Column(DateTime, default=func.now())
    notes           = Column(Text)

    events = relationship("CompanyEvent", back_populates="company")
    people = relationship("Person", back_populates="company")  # Added relationship

class Person(Base):
    __tablename__ = 'people'
    person_id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    title = Column(String(255))
    company_id = Column(Integer, ForeignKey('companies.company_id'))
    email = Column(String(255))
    phone = Column(String(50))
    linkedin = Column(String(255))
    division = Column(String(255))  # To track if they're in signage division
    relevance_score = Column(Float)
    last_updated = Column(DateTime, default=func.now())
    notes = Column(Text)
    
    company = relationship("Company", back_populates="people")

class AssociationEvent(Base):
    __tablename__ = 'association_events'
    id             = Column(Integer, primary_key=True)
    association_id = Column(Integer, ForeignKey('associations.association_id'))
    event_id       = Column(Integer, ForeignKey('events.event_id'))

    association = relationship("Association", back_populates="events")
    event       = relationship("Event",       back_populates="associations")

class CompanyEvent(Base):
    __tablename__ = 'company_events'
    id         = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey('companies.company_id'))
    event_id   = Column(Integer, ForeignKey('events.event_id'))

    company = relationship("Company", back_populates="events")
    event   = relationship("Event",   back_populates="companies")

class SearchQuery(Base):
    __tablename__ = 'search_queries'
    query_id    = Column(Integer, primary_key=True)
    query_text  = Column(String(255), nullable=False)
    query_date  = Column(DateTime, default=func.now())
    query_source= Column(String(100))
    results_count = Column(Integer)
    notes       = Column(Text)

class Message(Base):
    __tablename__ = 'messages'
    message_id = Column(Integer, primary_key=True)
    person_id = Column(Integer, ForeignKey('people.person_id'))
    message_type = Column(String(50))  # e.g., 'linkedin_connect', 'linkedin_followup', 'email'
    subject = Column(String(255))
    content = Column(Text, nullable=False)
    created_date = Column(DateTime, default=func.now())
    sent_date = Column(DateTime)
    status = Column(String(50), default='draft')  # draft, sent, responded, etc.
    response = Column(Text)
    notes = Column(Text)
    
    # Relationship to Person
    person = relationship("Person", backref="messages")

def init_db():
    Base.metadata.create_all(engine)
    return engine

def get_session():
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=engine)
    return Session()