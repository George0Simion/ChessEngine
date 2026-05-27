from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Legătura către rating-ul utilizatorului
    rating = db.relationship('Rating', backref='user', uselist=False, cascade="all, delete-orphan")

class Rating(db.Model):
    __tablename__ = 'ratings'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Valorile de start obligatorii pentru Glicko-2 din specificații
    rating = db.Column(db.Float, default=1500.0)
    rd = db.Column(db.Float, default=350.0)
    vol = db.Column(db.Float, default=0.06)

class Game(db.Model):
    __tablename__ = 'games'
    
    id = db.Column(db.Integer, primary_key=True)
    white_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True) # Null = a jucat botul
    black_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True) # Null = a jucat botul
    
    status = db.Column(db.String(20), default='active') # active, checkmate, stalemate, draw_repetition, etc.
    winner = db.Column(db.String(10), nullable=True) # white, black, sau null pentru remiza
    
    # Vom salva istoricul mutărilor în format text (ex: "e2e4,e7e5,g1f3")
    moves_history = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)