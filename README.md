# FacilityOps Pulse

An AI-powered Facility and IT Service Management platform that helps organizations submit, track, prioritize, assign, and analyze facility maintenance and IT support requests.

---

## Features

| Module | Description |
|---|---|
| Authentication | Role-based login (Requester, Technician, Administrator) |
| Request Submission | Structured forms with category, location, and description |
| AI Classification | Groq LLM auto-categorizes request type and department |
| AI Priority | LLM-recommended priority based on request content |
| Duplicate Detection | Sentence Transformer embeddings find similar open requests |
| Assignment | Admins assign requests to technicians |
| Status History | Full audit trail of every status change |
| Analytics Dashboard | Plotly charts — volume, SLA, resolution time, technician load |
| AI Reports | LLM-generated management summaries from live data |

---

## Tech Stack

- **Python 3.11+**
- **Streamlit** — UI framework
- **PostgreSQL** — relational database
- **SQLAlchemy 2.x** — ORM
- **Alembic** — database migrations
- **Groq API** — LLM features (classification, priority, reports)
- **Sentence Transformers** — semantic similarity / duplicate detection
- **Pandas + Plotly** — analytics and charts
- **bcrypt** — password hashing

---

## Project Structure

```
FacilityOps-Pulse/
├── app.py                        # Streamlit entry point / router
├── requirements.txt
├── .env.example                  # Config template
├── .gitignore
│
├── core/                         # Cross-cutting utilities
│   ├── __init__.py
│   ├── config.py                 # Environment variable loader
│   ├── logger.py                 # Centralized logging setup
│   └── security.py               # Password hashing, session helpers
│
├── database/                     # Database layer
│   ├── __init__.py
│   ├── connection.py             # SQLAlchemy engine + session factory
│   ├── models/
│   │   ├── __init__.py
│   │   ├── user.py               # User model
│   │   ├── request.py            # ServiceRequest model
│   │   ├── assignment.py         # Assignment model
│   │   └── status_history.py     # StatusHistory model
│   └── crud/
│       ├── __init__.py
│       ├── user_crud.py          # User DB operations
│       ├── request_crud.py       # Request DB operations
│       ├── assignment_crud.py    # Assignment DB operations
│       └── history_crud.py       # Status history operations
│
├── services/                     # External service integrations
│   └── ai/
│       ├── __init__.py
│       ├── groq_client.py        # Groq API wrapper
│       ├── classifier.py         # Request type + department classification
│       ├── priority_advisor.py   # AI priority recommendation
│       ├── similarity.py         # Embedding-based duplicate detection
│       └── report_generator.py  # AI management report generation
│
├── business/                     # Business logic layer
│   ├── __init__.py
│   ├── request_service.py        # Request lifecycle orchestration
│   ├── user_service.py           # User management logic
│   └── analytics_service.py     # Data aggregation for dashboards
│
├── app/                          # Streamlit UI layer
│   ├── __init__.py
│   ├── components/
│   │   ├── __init__.py
│   │   ├── layout.py             # Page layout, header, sidebar
│   │   ├── tables.py             # Reusable data table components
│   │   └── charts.py             # Reusable Plotly chart components
│   └── pages/
│       ├── __init__.py
│       ├── auth.py               # Login / registration page
│       ├── requester.py          # Requester dashboard + submit form
│       ├── technician.py         # Technician work queue
│       └── admin.py              # Admin dashboard + management
│
└── logs/                         # Log files (git-ignored)
    └── .gitkeep
```

---

## Quick Start

### 1. Prerequisites

- Python 3.11 or higher
- PostgreSQL 14 or higher running locally (or remote)
- A [Groq API key](https://console.groq.com) (free tier available)

### 2. Clone and set up virtual environment

```bash
git clone <your-repo-url>
cd FacilityOps-Pulse

python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

> The first run will also download the Sentence Transformer embedding model (~90 MB) automatically.

### 4. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and fill in:
- `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` — your PostgreSQL credentials
- `GROQ_API_KEY` — your Groq API key
- `SESSION_SECRET_KEY` — generate with `python -c "import secrets; print(secrets.token_hex(32))"`

### 5. Set up PostgreSQL

```sql
-- Connect as postgres superuser
CREATE DATABASE facilityops_pulse;
CREATE USER facilityops_user WITH PASSWORD 'your_secure_password_here';
GRANT ALL PRIVILEGES ON DATABASE facilityops_pulse TO facilityops_user;
```

### 6. Initialize database tables

```bash
python -c "from database.connection import init_db; init_db()"
```

This creates all tables and seeds a default admin account:
- **Username:** `admin`
- **Password:** `Admin@123`
- Change the admin password immediately after first login.

### 7. Start the application

```bash
streamlit run app.py
```

Open `http://localhost:8501` in your browser.

---

## Configuration Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `DB_HOST` | Yes | `localhost` | PostgreSQL host |
| `DB_PORT` | No | `5432` | PostgreSQL port |
| `DB_NAME` | Yes | — | Database name |
| `DB_USER` | Yes | — | Database user |
| `DB_PASSWORD` | Yes | — | Database password |
| `GROQ_API_KEY` | Yes* | — | Groq API key (*required for AI features) |
| `GROQ_MODEL` | No | `llama-3.3-70b-versatile` | Groq model name |
| `EMBEDDING_MODEL` | No | `all-MiniLM-L6-v2` | HuggingFace model for embeddings |
| `SESSION_SECRET_KEY` | Yes | — | Random hex secret for sessions |
| `ENABLE_AI_FEATURES` | No | `true` | Toggle all AI features on/off |
| `ENABLE_SEMANTIC_SEARCH` | No | `true` | Toggle duplicate detection on/off |
| `LOG_LEVEL` | No | `INFO` | Logging verbosity |

---

## User Roles

| Role | Capabilities |
|---|---|
| **Requester** | Submit requests, view own request history, track status |
| **Technician** | View assigned requests, update status and add work notes |
| **Administrator** | Full access: manage users, assign requests, view analytics, generate AI reports |

---

## License

This project is provided as an independent MVP for demonstration and internal use.
