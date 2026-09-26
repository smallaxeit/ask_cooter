-- Create the Ask Cooter role, database, and enable pgvector.
-- Run as the postgres superuser (you'll be prompted for its password).
-- PG18 is on port 5433. In PowerShell, prefix the quoted path with & :
--
--   & "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -p 5433 -f scripts\bootstrap-db.sql
--
-- This matches DATABASE_URL in .env.example:
--   postgresql://cooter:cooter@localhost:5433/askcooter

-- Role + database. The password below is a published default and is only
-- appropriate for a Postgres that listens on localhost. If this instance is
-- reachable from anywhere else, change it here and in .env to match.
CREATE ROLE cooter WITH LOGIN PASSWORD 'cooter';
CREATE DATABASE askcooter OWNER cooter;

-- Enable the extension inside the new database. \connect switches DB in psql.
\connect askcooter
CREATE EXTENSION IF NOT EXISTS vector;
GRANT ALL ON SCHEMA public TO cooter;
