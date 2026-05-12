from app.db import engine
from sqlalchemy import text

# Add the column if it doesn't exist
with engine.connect() as conn:
    # Check if the column exists (optional)
    # We'll just try to add it and catch the exception if it already exists
    try:
        conn.execute(text("ALTER TABLE transcriptions ADD COLUMN preprocessed_audio_file_path TEXT"))
        conn.commit()
        print("Column added successfully.")
    except Exception as e:
        print(f"Error: {e}")
        # If the column already exists, we can ignore
        if "duplicate column name" in str(e).lower() or "already exists" in str(e).lower():
            print("Column already exists.")
        else:
            raise