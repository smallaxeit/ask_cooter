# pgvector build artifacts

`vector--0.8.6.sql` and `vector.control` are unmodified files from
[pgvector](https://github.com/pgvector/pgvector) v0.8.6, redistributed here so
`CREATE EXTENSION vector` works on a Windows PG18 install without rebuilding
them. They are covered by `LICENSE` in this directory (the PostgreSQL License),
not by the PolyForm Noncommercial license at the repository root.

`vector.dll` is not committed — it is platform-specific and embeds the builder's
absolute paths. Build it locally with `scripts/install-pgvector.ps1`.
