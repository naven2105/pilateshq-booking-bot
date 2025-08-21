import os
import psycopg2
from psycopg2.extras import RealDictCursor

# Read connection URL from environment variable
# Render provides DATABASE_URL automatically
DATABASE_URL = os.getenv("DATABASE_URL")

def get_connection():
    """Create a new database connection."""
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL is not set in environment variables.")
    
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return conn


def init_db():
    """Initialise the database schema if not already created."""
    conn = get_connection()
    cur = conn.cursor()

    # Create clients table if it doesn’t exist
    cur.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            id SERIAL PRIMARY KEY,
            name VARCHAR(100),
            phone VARCHAR(20) UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # You can later extend schema for bookings, reminders, etc.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id SERIAL PRIMARY KEY,
            client_id INT REFERENCES clients(id) ON DELETE CASCADE,
            class_type VARCHAR(50),
            booking_date TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    conn.commit()
    cur.close()
    conn.close()
    print("✅ Database initialised")


def add_client(name, phone):
    """Insert a new client, or return existing client if already in DB."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO clients (name, phone)
        VALUES (%s, %s)
        ON CONFLICT (phone) DO UPDATE SET name = EXCLUDED.name
        RETURNING *;
    """, (name, phone))

    client = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return client


def get_client_by_phone(phone):
    """Fetch client by phone number."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM clients WHERE phone = %s;", (phone,))
    client = cur.fetchone()

    cur.close()
    conn.close()
    return client
