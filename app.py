from flask import Flask, render_template, request, redirect, url_for, flash, session
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import date
from datetime import datetime
import urllib.parse as urlparse

# Inisialisasi Flask app
app = Flask(__name__)
app.secret_key = 'rahasia_super_aman'

# Konfigurasi folder upload dan ekstensi yang diizinkan
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Buat folder static/uploads kalau belum ada
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Fungsi untuk mengecek ekstensi file yang diizinkan
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Fungsi koneksi ke database PostgreSQL
ddef get_db_connection():
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        raise Exception("DATABASE_URL not set!")

    # Parsing DATABASE_URL agar bisa digunakan psycopg2
    urlparse.uses_netloc.append("postgres")
    parsed_url = urlparse.urlparse(db_url)

    return psycopg2.connect(
        dbname=parsed_url.path[1:],
        user=parsed_url.username,
        password=parsed_url.password,
        host=parsed_url.hostname,
        port=parsed_url.port
    )
    


# ================== ROUTES ==================

@app.route('/')
def index():
    return redirect(url_for('login'))

# ----------- LOGIN -----------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cur.fetchone()
        conn.close()
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['role'] = user['role']
            flash('Login berhasil!', 'success')
            return redirect(url_for('dashboard'))
        flash('Email atau password salah!', 'danger')
    return render_template('login.html')

# ----------- REGISTER -----------
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        full_name = request.form['full_name']
        email = request.form['email']
        password = request.form['password']
        hashed_pw = generate_password_hash(password)
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("INSERT INTO users (full_name, email, password) VALUES (%s, %s, %s)", (full_name, email, hashed_pw))
            conn.commit()
            flash('Registrasi berhasil!', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            conn.rollback()
            print("ERROR:", e)
            flash('Email sudah terdaftar atau terjadi kesalahan!', 'danger')
        finally:
            conn.close()
    return render_template('register.html')

# ----------- DASHBOARD -----------
@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT full_name FROM users WHERE id = %s", (session['user_id'],))
    user = cur.fetchone()
    conn.close()

    return render_template('dashboard.html', user=user)

# ----------- BUKU (LIST) -----------
@app.route('/books')
def books():
    keyword = request.args.get('q', '')
    filter_stock = request.args.get('stock', '')
    category = request.args.get('category', '')
    
    conn = get_db_connection()
    cur = conn.cursor()

    # Query utama dengan filter dinamis
    query = "SELECT * FROM books WHERE 1=1"
    params = []

    # Filter pencarian
    if keyword:
        query += " AND (LOWER(title) LIKE %s OR LOWER(author) LIKE %s)"
        like_kw = f"%{keyword.lower()}%"
        params += [like_kw, like_kw]

    # Filter stok
    if filter_stock == 'available':
        query += " AND stock > 0"
    elif filter_stock == 'empty':
        query += " AND stock = 0"

    # Filter kategori
    if category:
        query += " AND category = %s"
        params.append(category)

    cur.execute(query, tuple(params))
    books = cur.fetchall()

    # Ambil daftar kategori unik untuk dropdown filter
    cur.execute("SELECT DISTINCT category FROM books ORDER BY category")
    categories = [row['category'] for row in cur.fetchall()]
    
    conn.close()

    return render_template(
        'books.html',
        books=books,
        keyword=keyword,
        filter_stock=filter_stock,
        category=category,
        categories=categories
    )


@app.route('/book/<int:book_id>')
def book_detail(book_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM books WHERE id = %s", (book_id,))
    book = cur.fetchone()
    conn.close()

    if not book:
        flash("Buku tidak ditemukan.", "danger")
        return redirect(url_for('books'))

    return render_template('book_detail.html', book=book)



# ----------- PINJAM BUKU -----------
@app.route('/borrow/<int:book_id>', methods=['POST'])
def borrow(book_id):
    if 'user_id' not in session:
        flash('Anda harus login untuk meminjam buku.', 'danger')
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor()

    # Kurangi stok dan catat peminjaman
    cur.execute("UPDATE books SET stock = stock - 1 WHERE id = %s AND stock > 0", (book_id,))
    cur.execute("""
        INSERT INTO borrowings (user_id, book_id, borrow_date, status)
        VALUES (%s, %s, CURRENT_DATE, 'Dipinjam')
    """, (session['user_id'], book_id))

    conn.commit()
    conn.close()

    flash('Buku berhasil dipinjam!', 'success')
    return redirect(url_for('books'))


# ----------- TAMBAH BUKU (dengan upload gambar) -----------
@app.route('/add_book', methods=['GET', 'POST'])
def add_book():
    if request.method == 'POST':
        title = request.form['title']
        author = request.form['author']
        stock = request.form['stock']
        file = request.files['image']

        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            image_url = '/' + file_path.replace('\\', '/')
        else:
            image_url = None

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO books (title, author, stock, image_url)
            VALUES (%s, %s, %s, %s)
        """, (title, author, stock, image_url))
        conn.commit()
        conn.close()

        flash("Buku berhasil ditambahkan!", "success")
        return redirect(url_for('books'))

    return render_template('add_book.html')


@app.route('/return/<int:borrow_id>', methods=['POST'])
def return_book(borrow_id):
    if 'user_id' not in session:
        flash("Kamu harus login dulu!", 'warning')
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor()

    # Ambil info peminjaman
    cur.execute("SELECT * FROM borrowings WHERE id = %s AND return_date IS NULL", (borrow_id,))
    borrowing = cur.fetchone()
    if not borrowing:
        flash("Peminjaman tidak ditemukan atau sudah dikembalikan!", 'danger')
        conn.close()
        return redirect(url_for('history'))

    # Update pengembalian
    cur.execute("""
        UPDATE borrowings
        SET return_date = %s
        WHERE id = %s
    """, (date.today(), borrow_id))

    # Tambah stok buku kembali
    cur.execute("UPDATE books SET stock = stock + 1 WHERE id = %s", (borrowing['book_id'],))
    conn.commit()
    conn.close()

    flash("Buku berhasil dikembalikan!", 'success')
    return redirect(url_for('history'))

@app.route('/history')
def history():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT b.id, books.title, b.borrow_date, b.return_date
        FROM borrowings b
        JOIN books ON b.book_id = books.id
        WHERE b.user_id = %s
        ORDER BY b.borrow_date DESC
    """, (session['user_id'],))
    borrowings = cur.fetchall()
    conn.close()
    return render_template('history.html', borrowings=borrowings)

# ----------- LOGOUT -----------
@app.route('/logout')
def logout():
    session.clear()
    flash('Kamu telah logout!', 'info')
    return redirect(url_for('login'))

# ===========================================

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
