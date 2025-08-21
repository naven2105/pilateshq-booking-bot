# init_db.py
from db import engine, Base
import models  # noqa: F401  (ensures models are imported so tables are registered)

if __name__ == "__main__":
    Base.metadata.create_all(bind=engine)
    print("✅ DB schema created (clients)")
