from flask import Flask, render_template, request, redirect, session, url_for, flash, send_file
import boto3, uuid, os, qrcode, io, threading, webbrowser
from werkzeug.security import generate_password_hash, check_password_hash
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET', 'super-secret-key')

# AWS Setup
dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
sns = boto3.client('sns', region_name='us-east-1')

USER_TABLE = 'MovieMagicUsers'
BOOKING_TABLE = 'MovieMagicBookings'
SNS_TOPIC_ARN = 'your-sns-topic-arn:aws:sns:us-east-1:222634386387:MovieTicketNotifications

table_users = dynamodb.Table(USER_TABLE)
table_bookings = dynamodb.Table(BOOKING_TABLE)

# ---------- Movie Data ----------
MOVIES = [
    {
        "title": "Getha Govindam",
        "price": 180,
        "image": "gethagovindam.jpg",
        "theaters": [
            {"name": "PVR Cinemas", "times": ["10:00 AM", "1:30 PM", "6:00 PM"]},
            {"name": "INOX", "times": ["11:15 AM", "2:45 PM", "8:30 PM"]}
        ]
    },
    {
        "title": "Orange",
        "price": 250,
        "image": "orange.jpg",
        "theaters": [
            {"name": "PVR Cinemas", "times": ["10:00 AM", "1:30 PM", "6:00 PM"]},
            {"name": "INOX", "times": ["11:15 AM", "2:45 PM", "8:30 PM"]}
        ]
    },
    {
        "title": "Junior",
        "price": 200,
        "image": "junior.jpg",
        "theaters": [
            {"name": "Asian Cinemas", "times": ["12:00 PM", "3:30 PM", "7:00 PM"]},
            {"name": "Sree Ramulu", "times": ["1:00 PM", "4:00 PM", "9:00 PM"]}
        ]
    }
]

# ---------- Routes ----------
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = generate_password_hash(request.form['password'])

        if User.query.filter_by(email=email).first():
            flash('Email already registered.')
        else:
            user = User(name=name, email=email, password=password)
            db.session.add(user)
            db.session.commit()
            flash('Registration successful. Please login.')
            return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password_input = request.form['password']
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password_input):
            session['email'] = user.email
            return redirect(url_for('home'))
        else:
            flash('Invalid credentials.')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully.')
    return redirect(url_for('index'))

@app.route('/home')
def home():
    if 'email' not in session:
        return redirect(url_for('login'))
    return render_template('home.html', movies=MOVIES)

@app.route('/booking/<title>', methods=['GET', 'POST'])
def booking(title):
    movie = next((m for m in MOVIES if m['title'] == title), None)
    if not movie:
        return "Movie not found", 404

    if request.method == 'POST':
        seating = request.form.get('seating')
        if seating:
            theater, time = seating.split('|')
            session['booking'] = {
                'movie_title': movie['title'],
                'movie_image': movie['image'],
                'movie_price': movie['price'],
                'theater': theater,
                'time': time
            }
            return redirect(url_for('seating'))

    return render_template('booking.html', movie=movie)

@app.route('/seating', methods=['GET', 'POST'])
def seating():
    booking = session.get('booking')
    if not booking:
        return redirect(url_for('home'))

    movie = next((m for m in MOVIES if m['title'] == booking['movie_title']), None)
    if not movie:
        return "Movie not found", 404

    if request.method == 'POST':
        seats = request.form.get('selected_seats')
        if seats:
            booking['seats'] = seats
            session['booking'] = booking

            user = User.query.filter_by(email=session['email']).first()
            total_price = booking['movie_price'] * len(seats.split(','))

            new_booking = Booking(
                booking_id=str(uuid.uuid4())[:8],
                user_id=user.id,
                movie=booking['movie_title'],
                theater=booking['theater'],
                time=booking['time'],
                seats=seats,
                price=total_price
            )
            db.session.add(new_booking)
            db.session.commit()
            return redirect(url_for('payment', booking_id=new_booking.booking_id))

    return render_template('seating.html', movie=movie, theater=booking['theater'], time=booking['time'])

@app.route('/payment', methods=['GET', 'POST'])
def payment():
    booking = session.get('booking')
    if not booking or 'seats' not in booking:
        return redirect(url_for('home'))

    total_price = booking['movie_price'] * len(booking['seats'].split(','))

    if request.method == 'POST':
        user = User.query.filter_by(email=session['email']).first()
        new_booking = Booking(
            booking_id=str(uuid.uuid4())[:8],
            user_id=user.id,
            movie=booking['movie_title'],
            theater=booking['theater'],
            time=booking['time'],
            seats=booking['seats'],
            price=total_price
        )
        db.session.add(new_booking)
        db.session.commit()
        session['booking_id'] = new_booking.booking_id
        return redirect(url_for('ticket'))

    return render_template('payment.html',
        movie={'title': booking['movie_title'], 'image': booking['movie_image']},
        theater=booking['theater'],
        time=booking['time'],
        seats=booking['seats'],
        price=total_price
    )


@app.route('/ticket')
def ticket():
    booking_id = session.get('booking_id')
    if not booking_id:
        return redirect(url_for('home'))

    booking = Booking.query.filter_by(booking_id=booking_id).first()
    if not booking:
        return "Booking not found", 404

    return render_template('ticket.html', movie={
        'title': booking.movie,
        'image': next((m['image'] for m in MOVIES if m['title'] == booking.movie), ''),
    }, seats=booking.seats, theater=booking.theater, time=booking.time,
       booking_id=booking.booking_id, total_price=booking.price)


@app.route('/dashboard')
def dashboard():
    if 'email' not in session:
        return redirect(url_for('login'))
    user = User.query.filter_by(email=session['email']).first()
    bookings = Booking.query.filter_by(user_id=user.id).order_by(Booking.created_at.desc()).all()
    return render_template('dashboard.html', bookings=bookings, user=user)
@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/services')
def services():
    return render_template('services.html')


# ---------- Auto Browser Launch ----------
def open_browser():
    webbrowser.open("http://127.0.0.1:5000/")

if __name__ == '__main__':
    threading.Timer(1.5, open_browser).start()
app.run(debug=True, host='0.0.0.0', port=5000)
