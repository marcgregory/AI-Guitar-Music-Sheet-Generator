#!/usr/bin/env python3
"""
Validate SQL migration files for basic syntax.
"""
import os
import glob

def validate_sql_file(file_path):
    """Basic validation of SQL file."""
    try:
        with open(file_path, 'r') as f:
            content = f.read()

        # Check for obvious issues
        if not content.strip():
            return False, "File is empty"

        # Check for unbalanced $$ quotes (simple check)
        dollar_count = content.count('$$')
        if dollar_count % 2 != 0:
            return False, f"Unbalanced $$ quotes: {dollar_count} found"

        # Check for unbalanced BEGIN/END in DO blocks (simple check)
        do_begin_count = content.upper().count('DO $$')
        do_end_count = content.upper().count('END $$;')
        if do_begin_count != do_end_count:
            return False, f"Mismatched DO blocks: {do_begin_count} BEGIN, {do_end_count} END"

        return True, "OK"
    except Exception as e:
        return False, f"Error reading file: {str(e)}"

def main():
    migrations_dir = os.path.join(os.path.dirname(__file__), "migrations")
    if not os.path.exists(migrations_dir):
        print("Migrations directory not found")
        return

    migration_files = sorted(glob.glob(os.path.join(migrations_dir, "*.sql")))

    print(f"Validating {len(migration_files)} migration files...")

    all_valid = True
    for migration_file in migration_files:
        valid, message = validate_sql_file(migration_file)
        status = "PASS" if valid else "FAIL"
        print(f"{status}: {os.path.basename(migration_file)} - {message}")
        if not valid:
            all_valid = False

    if all_valid:
        print("\nAll migrations validated successfully!")
    else:
        print("\nSome migrations failed validation!")
        return 1

    return 0

if __name__ == "__main__":
    exit(main())