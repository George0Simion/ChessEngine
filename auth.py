from flask import Blueprint, request, jsonify, current_app
from werkzeug.security import generate_password_hash, check_password_hash
import jwt
from datetime import datetime, timedelta
from functools import wraps

from models import db, User, Rating, Game

# Creăm un "Blueprint" pentru a grupa rutele de autentificare
auth_bp = Blueprint('auth', __name__, url_prefix='/auth')


def _jwt_secret() -> str:
    """Key used to sign/verify JWTs. Prefer JWT_SECRET_KEY, fall back to
    SECRET_KEY so a single configured secret still works. The multiplayer
    service resolves the same value so tokens validate across services."""
    return current_app.config.get('JWT_SECRET_KEY') or current_app.config['SECRET_KEY']

def token_required(f):
    """Decorator pentru a proteja rutele care necesită utilizator logat."""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        # Token-ul trebuie trimis în header ca "Authorization: Bearer <token>"
        if 'Authorization' in request.headers:
            parts = request.headers['Authorization'].split()
            if len(parts) == 2 and parts[0] == 'Bearer':
                token = parts[1]
        
        if not token:
            return jsonify({'ok': False, 'error': 'Token lipsă!'}), 401
        
        try:
            data = jwt.decode(token, _jwt_secret(), algorithms=["HS256"])
            current_user = User.query.get(data['user_id'])
            if not current_user:
                raise Exception("Utilizator invalid")
        except Exception as e:
            return jsonify({'ok': False, 'error': 'Token invalid sau expirat!'}), 401
            
        return f(current_user, *args, **kwargs)
    return decorated

@auth_bp.post('/register')
def register():
    data = request.get_json(silent=True) or {}
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({'ok': False, 'error': 'Username și parola sunt obligatorii!'}), 400
        
    if User.query.filter_by(username=username).first():
        return jsonify({'ok': False, 'error': 'Username-ul există deja!'}), 400

    # Hash-uim parola pentru siguranță (pbkdf2 explicit — scrypt nu e disponibil pe Python 3.9 fără OpenSSL cu suport scrypt)
    hashed_password = generate_password_hash(password, method="pbkdf2:sha256")
    new_user = User(username=username, password_hash=hashed_password)
    db.session.add(new_user)
    db.session.flush() # Salvăm temporar pentru a obține ID-ul generat al userului

    # Setăm ratingul inițial strict conform specificațiilor Glicko-2
    new_rating = Rating(user_id=new_user.id, rating=1500.0, rd=350.0, vol=0.06)
    db.session.add(new_rating)
    
    db.session.commit()
    
    return jsonify({'ok': True, 'message': 'Cont creat cu succes!'}), 201

@auth_bp.post('/login')
def login():
    data = request.get_json(silent=True) or {}
    username = data.get('username')
    password = data.get('password')

    user = User.query.filter_by(username=username).first()
    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({'ok': False, 'error': 'Date de autentificare incorecte!'}), 401

    # Generăm JWT-ul valabil 7 zile
    token = jwt.encode({
        'user_id': user.id,
        'exp': datetime.utcnow() + timedelta(days=7)
    }, _jwt_secret(), algorithm="HS256")

    return jsonify({'ok': True, 'token': token, 'username': user.username})

@auth_bp.get('/me')
@token_required
def get_me(current_user):
    # Luăm ultimele 10 meciuri jucate pentru istoric
    recent_games = Game.query.filter(
        (Game.white_id == current_user.id) | (Game.black_id == current_user.id)
    ).order_by(Game.created_at.desc()).limit(10).all()

    history = []
    for g in recent_games:
        color = "white" if g.white_id == current_user.id else "black"
        history.append({
            "id": g.id,
            "color": color,
            "status": g.status,
            "winner": g.winner,
            "date": g.created_at.isoformat()
        })

    r = current_user.rating
    return jsonify({
        'ok': True,
        'user': {
            'username': current_user.username,
            'rating': round(r.rating) if r else 1500,
            'rd': round(r.rd) if r else 350,
        },
        'history': history
    })