# Opens a psql shell to the Ask Cooter database (PG18, port 5433).
# Prompts for the 'cooter' role password (default: cooter).
#   powershell -ExecutionPolicy Bypass -File scripts\db-shell.ps1
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U cooter -p 5433 -d askcooter
