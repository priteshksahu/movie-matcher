class MovieSwiper {
    constructor() {
        this.currentCard = null;
        this.startX = 0;
        this.currentX = 0;
        this.movies = [];
        this.currentIndex = 0;

        this.cardStack = document.getElementById('card-stack');
        this.skipButton = document.getElementById('skip-button');
        this.likeButton = document.getElementById('like-button');

        this.init();
    }

    async init() {
        await this.fetchMovies();
        this.setupEventListeners();
        this.showNextCard();
    }

    async fetchMovies() {
        try {
            const response = await fetch('/api/movies');
            this.movies = await response.json();
        } catch (error) {
            console.error('Error fetching movies:', error);
        }
    }

    setupEventListeners() {
        this.skipButton.addEventListener('click', () => this.handleSwipe('left'));
        this.likeButton.addEventListener('click', () => this.handleSwipe('right'));

        // Touch events
        this.cardStack.addEventListener('touchstart', (e) => this.handleTouchStart(e));
        this.cardStack.addEventListener('touchmove', (e) => this.handleTouchMove(e));
        this.cardStack.addEventListener('touchend', () => this.handleTouchEnd());
    }

    createMovieCard(movie) {
        const card = document.createElement('div');
        card.className = 'movie-card';
        card.innerHTML = `
            <img src="${movie.poster}" alt="${movie.title}">
            <div class="movie-info">
                <h2>${movie.title}</h2>
                <p>${movie.year}</p>
                <p>${movie.rating}</p>
            </div>
        `;
        return card;
    }

    showNextCard() {
        if (this.currentIndex >= this.movies.length) {
            this.currentIndex = 0;
            this.fetchMovies(); // Fetch new movies when we run out
        }

        const movie = this.movies[this.currentIndex];
        const card = this.createMovieCard(movie);
        this.cardStack.appendChild(card);
        this.currentCard = card;
    }

    handleSwipe(direction) {
        if (!this.currentCard) return;

        const swipeAnimation = this.currentCard.animate([
            { transform: 'translateX(0) rotate(0)' },
            { 
                transform: `translateX(${direction === 'left' ? '-' : ''}150%) rotate(${direction === 'left' ? '-' : ''}30deg)`
            }
        ], {
            duration: 300,
            easing: 'ease-out'
        });

        swipeAnimation.onfinish = () => {
            this.currentCard.remove();
            if (direction === 'right') {
                this.addToFavorites(this.movies[this.currentIndex].id);
            }
            this.currentIndex++;
            this.showNextCard();
        };
    }

    async addToFavorites(movieId) {
        try {
            await fetch('/api/favorite', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ movie_id: movieId })
            });
        } catch (error) {
            console.error('Error adding to favorites:', error);
        }
    }

    handleTouchStart(e) {
        this.startX = e.touches[0].clientX;
    }

    handleTouchMove(e) {
        if (!this.currentCard) return;
        
        this.currentX = e.touches[0].clientX;
        const deltaX = this.currentX - this.startX;
        const rotation = deltaX * 0.1;
        
        this.currentCard.style.transform = `translateX(${deltaX}px) rotate(${rotation}deg)`;
    }

    handleTouchEnd() {
        if (!this.currentCard) return;

        const deltaX = this.currentX - this.startX;
        if (Math.abs(deltaX) > 100) {
            this.handleSwipe(deltaX > 0 ? 'right' : 'left');
        } else {
            this.currentCard.style.transform = '';
        }
    }
}

// Initialize the MovieSwiper when the DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    new MovieSwiper();
}); 