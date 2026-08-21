# DocFlow AI — Phase 1

Phase 1 proves this path:

`FastAPI backend → Notion API → DOCUMENT INBOX → test record`

It deliberately does **not** yet include PDF extraction, AI analysis, approvals, email, or run logging. Those belong to later phases.

## Project files

- `main.py` defines the FastAPI application and its three endpoints.
- `config.py` loads configuration from `.env` using `python-dotenv` and Pydantic.
- `services/notion_service.py` is the single place that calls Notion's API.
- `models/schemas.py` defines the documented API response shapes.
- `requirements.txt` lists the Python packages to install. PyMuPDF is included now because it is part of the planned stack, but is not used until Phase 2.
- `.env` holds your local secret values; `.env.example` is the safe template.

## 1. Create and activate a virtual environment

Open PowerShell in this project folder, then run:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, run this once for the current window and activate again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

## 2. Install dependencies

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 3. Fill in `.env`

Open the `.env` file at the project root. Add the token and IDs only there:

```dotenv
NOTION_TOKEN=your_notion_token_here
DOCUMENT_INBOX_ID=your_document_inbox_id
APPROVAL_QUEUE_ID=your_approval_queue_id
RUN_LOG_ID=your_run_log_id
```

Find each ID by opening the **original** Notion database (not a linked view) in your browser. Its URL ends in a 32-character ID. Copy that final ID; hyphens are optional. Ensure the **DocFlow AI Backend** integration is connected to each of the three databases.

Never paste these values into source code or commit your completed `.env` file.

## 4. Run the server

With the virtual environment active:

```powershell
uvicorn main:app --reload
```

The server runs at `http://127.0.0.1:8000`.

## 5. Open Swagger documentation

Open [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs). Swagger lets you execute every endpoint from the browser.

## 6. Test the workflow

1. Open `GET /health`, choose **Try it out**, then **Execute**. You should receive:
   ```json
   {"status":"running","service":"DocFlow AI"}
   ```
2. Open `GET /notion/test` and execute it. A success response confirms the token and access to DOCUMENT INBOX, APPROVAL QUEUE, and RUN LOG.
3. Open `POST /documents/test` and execute it. It creates **DocFlow AI - Test Document** in DOCUMENT INBOX and returns a direct Notion page URL.

If Notion returns 401, recheck `NOTION_TOKEN`. For 404 or 403, make sure the database IDs are from original databases and that the integration has been added to each database's connections. The API uses Notion's current data-source endpoints internally, while still accepting the database IDs requested in `.env`.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Confirms FastAPI is running. |
| GET | `/notion/test` | Verifies the Notion token and all three database connections. |
| POST | `/documents/test` | Creates a test record in DOCUMENT INBOX. |

## Phase 1 completion check

Stop here after you have successfully created the test record. Test the endpoints and confirm the record appears in Notion before beginning Phase 2.
