from flask import Flask, render_template, jsonify, request, redirect, url_for
import requests
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import random
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import os
from typing import Dict, List
from cachetools import TTLCache, cached
import asyncio
import aiohttp

app = Flask(__name__)
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'movie-matcher-share-key')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'DATABASE_URL',
    'sqlite:///' + os.path.join(BASE_DIR, 'movies.db')
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
db = SQLAlchemy(app)

# OMDB API Configuration
OMDB_API_KEY = os.environ.get('OMDB_API_KEY', '44991f2d')
OMDB_BASE_URL = "https://www.omdbapi.com/"
OMDB_POSTER_URL = "https://img.omdbapi.com/"


def fetch_omdb_data(params: dict):
    """Fetch movie data from OMDb (used by favorites, watchlist, and listings)."""
    query = dict(params)
    query.setdefault('apikey', OMDB_API_KEY)
    try:
        response = requests.get(OMDB_BASE_URL, params=query, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get('Response') != 'False':
                return data
    except Exception as e:
        print(f"OMDB API Error: {str(e)}")
    return None

# Add after creating Flask app
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Database Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256))  # Increased length for password hash
    date_registered = db.Column(db.DateTime, default=datetime.utcnow)
    favorites = db.relationship('Favorite', backref='user', lazy=True, cascade="all, delete-orphan")
    watchlist = db.relationship('WatchLater', backref='user', lazy=True, cascade="all, delete-orphan")

    def __init__(self, username, email):
        self.username = username
        self.email = email

    def set_password(self, password):
        if not password:
            raise ValueError("Password cannot be empty")
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

class Favorite(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    movie_id = db.Column(db.String(20), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date_added = db.Column(db.DateTime, default=datetime.utcnow)

class WatchLater(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    movie_id = db.Column(db.String(20), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date_added = db.Column(db.DateTime, default=datetime.utcnow)

# Add global cache configurations
MOVIE_CACHE = TTLCache(maxsize=1000, ttl=3600)  # Cache movie data for 1 hour
SEARCH_CACHE = TTLCache(maxsize=100, ttl=300)   # Cache search results for 5 minutes

# Add session configuration
async def get_aiohttp_session():
    return aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=10),
        headers={'Accept': 'application/json'}
    )

# Update the cached_omdb_fetch function to use async/await
async def cached_omdb_fetch(movie_id: str, session) -> dict:
    """Fetch movie data with caching and async support"""
    if movie_id in MOVIE_CACHE:
        return MOVIE_CACHE[movie_id]
    
    params = {'i': movie_id, 'plot': 'full', 'apikey': OMDB_API_KEY}
    try:
        async with session.get(OMDB_BASE_URL, params=params) as response:
            if response.status == 200:
                data = await response.json()
                if data.get('Response') != 'False':
                    MOVIE_CACHE[movie_id] = data
                    return data
    except Exception as e:
        print(f"OMDB API Error for {movie_id}: {str(e)}")
    return None

# Update fetch_movie_details_parallel to use async/await
async def fetch_movie_details_parallel(movie_ids: List[str]) -> List[Dict]:
    """Fetch movie details in parallel using asyncio"""
    movies = []
    
    async with await get_aiohttp_session() as session:
        tasks = [cached_omdb_fetch(movie_id, session) for movie_id in movie_ids]
        results = await asyncio.gather(*tasks)
        
        for movie_id, movie_data in zip(movie_ids, results):
            if movie_data and movie_data.get('Response') != 'False':
                streaming = get_streaming_platforms(movie_data.get('Title', ''))
                movies.append({
                    'id': movie_id,
                    'title': movie_data.get('Title', ''),
                    'year': movie_data.get('Year', ''),
                    'poster': movie_data.get('Poster', ''),
                    'rating': movie_data.get('imdbRating', 'N/A'),
                    'plot': movie_data.get('Plot', ''),
                    'genre': movie_data.get('Genre', ''),
                    'runtime': movie_data.get('Runtime', ''),
                    'director': movie_data.get('Director', ''),
                    'actors': movie_data.get('Actors', ''),
                    'language': movie_data.get('Language', ''),
                    'country': movie_data.get('Country', ''),
                    'awards': movie_data.get('Awards', ''),
                    'metascore': movie_data.get('Metascore', 'N/A'),
                    'streaming': streaming
                })
    
    return movies

# Helper function to run async code in sync context
def run_async(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/health')
def health():
    return jsonify({"status": "ok"})

@app.route('/search')
def search():
    return render_template('search.html')

@app.route('/favorites')
@login_required
def favorites():
    return render_template('favorites.html')

@app.route('/watchlist')
@login_required
def watchlist():
    return render_template('watchlist.html')

@app.route('/movies')
def movies_page():
    return render_template('movies.html')

@app.route('/api/movies')
def get_movies():
    # Expanded list of popular movie IDs
    all_movies = [
        "tt0111161", "tt0068646", "tt0071562", "tt0468569", "tt0050083",
        "tt0108052", "tt0167260", "tt0110912", "tt0060196", "tt0137523",
        "tt0120737", "tt0109830", "tt0133093", "tt0080684", "tt0167261",
        "tt0073486", "tt0099685", "tt0047478", "tt0076759", "tt0120815",
        "tt0317248", "tt0114369", "tt0102926", "tt0038650", "tt0118799",
        "tt0110413", "tt0064116", "tt0245429", "tt0120586", "tt0816692"
    ]
    
    # Randomly select 10 movies
    selected_movies = random.sample(all_movies, min(10, len(all_movies)))
    
    movies = []
    for movie_id in selected_movies:
        movie_data = fetch_omdb_data({'i': movie_id, 'plot': 'full'})
        if movie_data:
            streaming = get_streaming_platforms(movie_data.get('Title', ''))
            movies.append({
                'id': movie_id,
                'title': movie_data.get('Title', ''),
                'year': movie_data.get('Year', ''),
                'poster': movie_data.get('Poster', ''),
                'rating': movie_data.get('imdbRating', 'N/A'),
                'plot': movie_data.get('Plot', ''),
                'genre': movie_data.get('Genre', ''),
                'runtime': movie_data.get('Runtime', ''),
                'director': movie_data.get('Director', ''),
                'actors': movie_data.get('Actors', ''),
                'awards': movie_data.get('Awards', ''),
                'metascore': movie_data.get('Metascore', 'N/A'),
                'streaming': streaming
            })
    
    return jsonify(movies)

@app.route('/api/movie/<movie_id>')
def get_movie_details(movie_id):
    movie_data = fetch_omdb_data({'i': movie_id, 'plot': 'full'})
    if movie_data:
        return jsonify(movie_data)
    return jsonify({"error": "Movie not found"})

@app.route('/api/favorite', methods=['POST'])
@login_required
def add_favorite():
    data = request.json
    movie_id = data.get('movie_id')
    new_favorite = Favorite(movie_id=movie_id, user_id=current_user.id)
    db.session.add(new_favorite)
    db.session.commit()
    return jsonify({"status": "success"})

@app.route('/api/search')
async def search_movies():
    query = request.args.get('q', '')
    language = request.args.get('language', '')
    region = request.args.get('region', '')
    
    if not query and not language and not region:
        return jsonify([])
    
    cache_key = f"{query}:{language}:{region}"
    if cache_key in SEARCH_CACHE:
        return jsonify(SEARCH_CACHE[cache_key])
    
    try:
        async with await get_aiohttp_session() as session:
            params = {
                's': query,
                'type': 'movie',
                'apikey': OMDB_API_KEY
            }
            
            async with session.get(OMDB_BASE_URL, params=params) as response:
                search_results = await response.json()
                
                if search_results and 'Search' in search_results:
                    movie_ids = [movie['imdbID'] for movie in search_results['Search'][:10]]
                    movies = await fetch_movie_details_parallel(movie_ids)
                    
                    if region or language:
                        filtered_movies = [
                            movie for movie in movies
                            if (not region or region.lower() in movie.get('country', '').lower()) and
                               (not language or language.lower() in movie.get('language', '').lower())
                        ]
                        SEARCH_CACHE[cache_key] = filtered_movies
                        return jsonify(filtered_movies)
                    
                    SEARCH_CACHE[cache_key] = movies
                    return jsonify(movies)
                
                return jsonify([])
    except Exception as e:
        print(f"Search error: {str(e)}")
        return jsonify([])

@app.route('/api/watchlist', methods=['POST'])
@login_required
def add_to_watchlist():
    data = request.json
    movie_id = data.get('movie_id')
    new_watchlist = WatchLater(movie_id=movie_id, user_id=current_user.id)
    db.session.add(new_watchlist)
    db.session.commit()
    return jsonify({"status": "success"})

@app.route('/api/favorites')
@login_required
def get_favorites():
    favorites = Favorite.query.filter_by(user_id=current_user.id).all()
    favorite_movies = []
    
    for favorite in favorites:
        movie_data = fetch_omdb_data({'i': favorite.movie_id})
        if movie_data:
            favorite_movies.append({
                'id': favorite.movie_id,
                'title': movie_data.get('Title', ''),
                'year': movie_data.get('Year', ''),
                'poster': movie_data.get('Poster', ''),
                'rating': movie_data.get('imdbRating', 'N/A'),
                'genre': movie_data.get('Genre', ''),
                'plot': movie_data.get('Plot', '')
            })
    
    return jsonify(favorite_movies)

@app.route('/api/favorite/<movie_id>', methods=['DELETE'])
@login_required
def remove_favorite(movie_id):
    Favorite.query.filter_by(user_id=current_user.id, movie_id=movie_id).delete()
    db.session.commit()
    return jsonify({"status": "success"})

@app.route('/api/watchlist')
@login_required
def get_watchlist():
    watchlist = WatchLater.query.filter_by(user_id=current_user.id).all()
    watchlist_movies = []
    
    for item in watchlist:
        movie_data = fetch_omdb_data({'i': item.movie_id})
        if movie_data:
            watchlist_movies.append({
                'id': item.movie_id,
                'title': movie_data.get('Title', ''),
                'year': movie_data.get('Year', ''),
                'poster': movie_data.get('Poster', ''),
                'rating': movie_data.get('imdbRating', 'N/A'),
                'genre': movie_data.get('Genre', ''),
                'plot': movie_data.get('Plot', '')
            })
    
    return jsonify(watchlist_movies)

@app.route('/api/watchlist/<movie_id>', methods=['DELETE'])
@login_required
def remove_from_watchlist(movie_id):
    WatchLater.query.filter_by(user_id=current_user.id, movie_id=movie_id).delete()
    db.session.commit()
    return jsonify({"status": "success"})

@app.route('/api/movies/category/<category>')
@cached(cache=TTLCache(maxsize=100, ttl=300))  # Cache category results for 5 minutes
def get_movies_by_category(category):
    category_movies = {
        'trending': [
            "tt1160419",  # Dune
            "tt9362722",  # Spider-Man: Across the Spider-Verse
            "tt15398776", # Oppenheimer
            "tt14230388", # Barbie
            "tt14209916", # Killers of the Flower Moon
            "tt13287846", # Napoleon
            "tt6166392",  # Saltburn
            "tt11145118"  # Poor Things
        ],
        'latest': [
            "tt15239678", # Civil War
            "tt21454134", # Godzilla x Kong: The New Empire
            "tt11304740", # Ghostbusters: Frozen Empire
            "tt11663228", # Dune: Part Two
            "tt11762114", # Madame Web
            "tt11291274", # The Fall Guy
            "tt11663808", # Mickey 17
            "tt14362112"  # Deadpool 3
        ],
        'action': [
            "tt10366206", # John Wick 4
            "tt9603212",  # Mission: Impossible - Dead Reckoning
            "tt1745960",  # Top Gun: Maverick
            "tt1630029",  # Avatar: The Way of Water
            "tt1877830",  # The Batman
            "tt6710474",  # Everything Everywhere All at Once
            "tt10366460", # TMNT: Mutant Mayhem
            "tt9362722"   # Spider-Man: Across the Spider-Verse
        ],
        'drama': [
            "tt14230388", # Barbie
            "tt15398776", # Oppenheimer
            "tt14209916", # Killers of the Flower Moon
            "tt6166392",  # Saltburn
            "tt11145118", # Poor Things
            "tt13238346", # Past Lives
            "tt5537002",  # Killers of the Flower Moon
            "tt9764362"   # The Menu
        ],
        'comedy': [
            "tt14230388", # Barbie
            "tt15789038", # Anyone But You
            "tt15671028", # No Hard Feelings
            "tt8589698",  # Teenage Mutant Ninja Turtles
            "tt11103470", # Air
            "tt15255876", # Bottoms
            "tt11145118", # Poor Things
            "tt15354916"  # Wonka
        ]
    }
    
    movie_ids = category_movies.get(category, [])
    movies = run_async(fetch_movie_details_parallel(movie_ids))
    return jsonify(movies)

@app.route('/api/movies/region/<region>')
@cached(cache=TTLCache(maxsize=100, ttl=300))  # Cache region results for 5 minutes
def get_movies_by_region(region):
    region_movies = {
        'india': [
            "tt15398776",  # Jawan
            "tt13751694",  # Pathaan
            "tt11663228",  # Animal
            "tt13751694",  # Dunki
            "tt13927994",  # Tiger 3
            "tt8178634",   # RRR
            "tt10701074",  # Pushpa: The Rise
            "tt9389998"    # K.G.F: Chapter 2
        ],
        'korea': [
            "tt6751668",   # Parasite
            "tt13634814",  # The Glory
            "tt13721828",  # Moving
            "tt26147432",  # Concrete Utopia
            "tt22297828",  # Kill Boksoon
            "tt15438246",  # The Roundup
            "tt15924700",  # Unlocked
            "tt15438228"   # Decision to Leave
        ],
        'japan': [
            "tt9362722",   # Suzume
            "tt14362112",  # Godzilla Minus One
            "tt21692408",  # The Boy and the Heron
            "tt14935892",  # Blue Giant
            "tt13616990",  # One Piece Film: Red
            "tt11460252",  # Demon Slayer: Mugen Train
            "tt9426210",   # Drive My Car
            "tt0245429"    # Spirited Away
        ],
        'france': [
            "tt13287846",  # Napoleon
            "tt15257160",  # Anatomy of a Fall
            "tt14230458",  # All Your Faces
            "tt14444726",  # The Three Musketeers
            "tt15398462",  # The Animal Kingdom
            "tt12573454",  # Asterix & Obelix
            "tt13833688",  # The Five Devils
            "tt9893250"    # Portrait of a Lady on Fire
        ],
        'spain': [
            "tt13560574",  # Society of the Snow
            "tt15671028",  # Through My Window
            "tt13833688",  # The Snow Girl
            "tt11649338",  # The Platform
            "tt8629748",   # Money Heist
            "tt4698684",   # Julieta
            "tt0245429",   # Pain and Glory
            "tt0457430"    # Pan's Labyrinth
        ]
    }
    
    movie_ids = region_movies.get(region.lower(), [])
    movies = run_async(fetch_movie_details_parallel(movie_ids))
    return jsonify(movies)

@app.route('/api/movies/language/<language>')
@cached(cache=TTLCache(maxsize=100, ttl=300))  # Cache language results for 5 minutes
def get_movies_by_language(language):
    language_movies = {
        'hindi': [
            "tt15398776",  # Jawan
            "tt13751694",  # Pathaan
            "tt11663228",  # Animal
            "tt13751694",  # Dunki
            "tt13927994",  # Tiger 3
            "tt10636048",  # The Kerala Story
            "tt15428134",  # Rocky Aur Rani
            "tt15354916"   # 12th Fail
        ],
        'tamil': [
            "tt12887858",  # Jailer
            "tt15239678",  # Leo
            "tt11698822",  # Vikram
            "tt11749798",  # PS 1
            "tt15679400",  # Varisu
            "tt10701074",  # Ponniyin Selvan
            "tt9260636",   # Master
            "tt9614460"    # Bigil
        ],
        'telugu': [
            "tt8178634",   # RRR
            "tt10701074",  # Pushpa
            "tt12261776",  # Salaar
            "tt13927994",  # Game Changer
            "tt12887858",  # Waltair Veerayya
            "tt15679400",  # Veera Simha Reddy
            "tt9389998",   # KGF 2
            "tt10579952"   # Baahubali 2
        ],
        'korean': [
            "tt6751668",   # Parasite
            "tt13634814",  # The Glory
            "tt13721828",  # Moving
            "tt26147432",  # Concrete Utopia
            "tt22297828",  # Kill Boksoon
            "tt15438246",  # The Roundup
            "tt15924700",  # Unlocked
            "tt15438228"   # Decision to Leave
        ],
        'japanese': [
            "tt9362722",   # Suzume
            "tt14362112",  # Godzilla Minus One
            "tt21692408",  # The Boy and the Heron
            "tt14935892",  # Blue Giant
            "tt13616990",  # One Piece Film: Red
            "tt11460252",  # Demon Slayer: Mugen Train
            "tt9426210",   # Drive My Car
            "tt0245429"    # Spirited Away
        ]
    }
    
    movie_ids = language_movies.get(language.lower(), [])
    movies = run_async(fetch_movie_details_parallel(movie_ids))
    return jsonify(movies)

# Update the streaming platforms cache
STREAMING_PLATFORMS_CACHE = {
    "Dune": ["HBO Max", "Prime Video"],
    "Barbie": ["Max", "Prime Video"],
    "Oppenheimer": ["Peacock", "Prime Video"],
    "Spider-Man: Across the Spider-Verse": ["Netflix", "Prime Video"],
    "The Batman": ["HBO Max", "Prime Video"],
    "Top Gun: Maverick": ["Paramount+", "Prime Video"],
    "Everything Everywhere All at Once": ["Showtime", "Prime Video"],
    "Poor Things": ["Hulu", "Prime Video"],
    "Saltburn": ["Prime Video"],
    "Napoleon": ["Apple TV+", "Prime Video"]
}

def get_streaming_platforms(movie_title: str) -> List[str]:
    """Get streaming platforms from cache"""
    return STREAMING_PLATFORMS_CACHE.get(movie_title, ["Available for rent on Prime Video"])

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    
    if request.method == 'POST':
        data = request.json
        user = User.query.filter_by(email=data.get('email')).first()
        
        if user and user.check_password(data.get('password')):
            login_user(user)
            return jsonify({"status": "success", "redirect": url_for('home')})
        
        return jsonify({"status": "error", "message": "Invalid email or password"}), 401
    
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    
    if request.method == 'POST':
        try:
            data = request.json
            
            # Validate required fields
            if not all([data.get('username'), data.get('email'), data.get('password')]):
                return jsonify({
                    "status": "error",
                    "message": "All fields are required"
                }), 400
            
            # Check if email exists
            if User.query.filter_by(email=data.get('email')).first():
                return jsonify({
                    "status": "error",
                    "message": "Email already registered"
                }), 400
            
            # Check if username exists
            if User.query.filter_by(username=data.get('username')).first():
                return jsonify({
                    "status": "error",
                    "message": "Username already taken"
                }), 400
            
            # Create new user
            user = User(
                username=data.get('username'),
                email=data.get('email')
            )
            user.set_password(data.get('password'))
            
            try:
                db.session.add(user)
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                print(f"Database error: {str(e)}")
                return jsonify({
                    "status": "error",
                    "message": "Database error occurred"
                }), 500
            
            login_user(user)
            return jsonify({
                "status": "success",
                "redirect": url_for('home')
            })
            
        except Exception as e:
            print(f"Registration error: {str(e)}")
            return jsonify({
                "status": "error",
                "message": "An error occurred during registration"
            }), 500
    
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))

def init_db():
    with app.app_context():
        db.create_all()

init_db()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', '0') == '1'
    app.run(debug=debug, host='0.0.0.0', port=port) 