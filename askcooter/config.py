"""Central configuration, sourced from environment variables (.env supported).

Import ``cfg`` and read attributes; nothing here talks to the network or the DB.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # dotenv is optional at runtime
    pass


@dataclass(frozen=True)
class Config:
    # Secrets / connections
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    voyage_api_key: str = os.getenv("VOYAGE_API_KEY", "")
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql://cooter:cooter@localhost:5433/askcooter"
    )

    # Source PDF + rendered images
    pdf_path: Path = Path(os.getenv("PDF_PATH", "Softail-1984-1999-Repair-Manual-Harley-Davidson.pdf"))
    image_dir: Path = Path(os.getenv("IMAGE_DIR", "data/pages"))
    render_dpi: int = int(os.getenv("RENDER_DPI", "150"))

    # Models
    extract_model: str = os.getenv("EXTRACT_MODEL", "claude-opus-5")
    answer_model: str = os.getenv("ANSWER_MODEL", "claude-opus-5")
    voyage_model: str = os.getenv("VOYAGE_MODEL", "voyage-3.5")
    embed_dim: int = int(os.getenv("EMBED_DIM", "1024"))

    # Retrieval
    search_limit: int = int(os.getenv("SEARCH_LIMIT", "5"))

    def require_ingest_keys(self) -> None:
        """Fail fast with a clear message if ingestion prerequisites are missing."""
        missing = []
        if not self.anthropic_api_key:
            missing.append("ANTHROPIC_API_KEY (vision extraction)")
        if not self.voyage_api_key:
            missing.append("VOYAGE_API_KEY (embeddings)")
        if missing:
            raise RuntimeError(
                "Missing required environment variables for ingestion:\n  - "
                + "\n  - ".join(missing)
                + "\nSet them in your environment or in a .env file (see .env.example)."
            )


cfg = Config()
