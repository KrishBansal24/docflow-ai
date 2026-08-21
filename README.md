# 📄 DocFlow AI

DocFlow AI is an AI-powered document-to-action automation system for small businesses. It is being built to turn business PDFs from files that someone must remember to read into structured, traceable workflows that can move toward the right action.

Today, the project has a working FastAPI foundation, a verified Notion connection, and a safe PDF upload and text-extraction pipeline. The AI, approval, and external-action stages described below are the product vision—not claims about functionality that exists today.

## 🚀 Project Overview

Small businesses receive supplier invoices, utility bills, vendor quotations, payment reminders, and other time-sensitive documents every day. The manual work is rarely difficult, but it is repetitive: someone has to open each PDF, understand it, decide who should act, and remember to follow up.

DocFlow AI is designed to reduce that overhead. Its central idea is that a document should not merely be stored—it should become an actionable workflow. The backend will progressively validate a document, understand its contents, identify the appropriate next action, route uncertain decisions to a person, and retain a useful record of what happened.

## ❗ The Problem

The traditional document workflow often looks like this:

```text
Business receives a document
        ↓
Employee opens the PDF
        ↓
Employee reads and interprets it
        ↓
Employee extracts important details
        ↓
Employee decides what action is needed
        ↓
Employee contacts the right person
        ↓
Employee remembers to follow up
```

This creates repetitive work, consumes time, invites human error, and makes deadlines easier to miss. Documents may be forgotten in inboxes, responses may be delayed, and it can be difficult to see which actions are pending or why a decision was made.

## 💡 The Solution

Traditional document storage stops here:

```text
Document → Stored → A human must remember what to do
```

The DocFlow AI vision continues the process:

```text
Document → Processed → Understood → Key information extracted
         → Required action identified → Human approval when needed
         → Action performed → Audit trail retained
```

This is document-to-action automation: using a document as the starting point for a controlled business workflow, not simply as an attachment in a folder.

## 🧠 How DocFlow AI Works

The following is the complete intended workflow. Steps marked **Planned** are not implemented yet.

### 1. Document upload — implemented

A user uploads a business PDF, such as an invoice, utility bill, vendor quotation, or payment reminder, through the FastAPI API.

### 2. Document validation — implemented

The backend checks that a file was supplied, has a `.pdf` extension, has an accepted content type when available, is not empty, is within the configured size limit, and can actually be opened as a PDF. A renamed non-PDF or corrupted file is rejected safely.

### 3. Text extraction — implemented

PyMuPDF extracts any readable text and the backend returns the filename, page count, character count, and SHA-256 hash. A valid image-only/scanned PDF is accepted, but is flagged with `needs_human_review: true` because OCR is not part of the current implementation.

### 4. Duplicate detection — planned

The SHA-256 hash generated today will later be used to detect whether the same document has already been processed. No duplicate lookup or blocking is implemented yet.

### 5. AI document understanding — planned

AI will eventually interpret extracted text and return structured information such as document type, vendor/company, amount, reference number, due date, priority, and suggested action.

### 6. Notion workflow — planned beyond the Phase 1 connection

The backend can currently verify access to the connected Notion databases and create a manual test record in **DOCUMENT INBOX**. It does **not** yet save uploaded PDFs or processed results there automatically.

The planned Notion workspace will let people view processed documents, understand AI recommendations, review pending actions, approve or reject decisions, and inspect workflow history.

### 7. Human approval — planned

Important, risky, uncertain, or low-confidence decisions should not be automated blindly. These will be routed to the Notion Approval Queue for a human decision.

### 8. External action — planned

After approval, the backend will eventually perform real actions outside Notion, such as sending a notification email to a finance manager.

### 9. Run log — planned beyond the Phase 1 connection

The Run Log database connection is currently verified by the Notion test endpoint. Automated event logging is not implemented yet. The final audit trail is intended to record events such as document received, processed, analyzed, approval requested, approved, action sent, and action failed.

## 🏗️ System Architecture

```text
                         ┌───────────────┐
                         │ Business User │
                         └───────┬───────┘
                                 │ upload PDF
                                 ▼
                         ┌───────────────┐
                         │ FastAPI       │
                         │ Backend       │
                         └───────┬───────┘
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │ PDF Validation &        │
                    │ PyMuPDF Text Extraction │
                    │      (Implemented)      │
                    └───────────┬────────────┘
                                │
                ┌───────────────┴────────────────┐
                ▼                                ▼
     ┌─────────────────────┐           ┌─────────────────────┐
     │ JSON API response   │           │ Notion connection   │
     │   (Implemented)     │           │ Phase 1 implemented │
     └─────────────────────┘           └──────────┬──────────┘
                                                   │
                                                   ▼
                                      ┌─────────────────────┐
                                      │ AI / Approval /      │
                                      │ External action /    │
                                      │ Run Log (Planned)    │
                                      └─────────────────────┘
```

## 🔄 Current Workflow

What works now when calling `POST /documents/upload`:

```text
PDF upload
    ↓
File validation
    ↓
PDF verification with PyMuPDF
    ↓
SHA-256 hash generation
    ↓
Readable text extraction
    ↓
Page count and character count
    ↓
JSON API response
```

For an image-only or scanned PDF:

```text
Valid PDF → No readable text → needs_human_review = true → OCR may be required later
```

## 📌 Current Project Status

**Phase 1: Completed** — FastAPI setup and Notion connection foundation.

**Phase 2: Completed** — PDF upload, validation, hashing, and text extraction.

The project currently supports:

- FastAPI backend and Swagger documentation
- Environment-based configuration
- Notion API connection checks for DOCUMENT INBOX, APPROVAL QUEUE, and RUN LOG
- Creation of a manual test record in DOCUMENT INBOX
- PDF upload and validation
- Text extraction with PyMuPDF
- Page and character counts
- SHA-256 file hashing
- Basic, human-readable API error handling

The project does **not** yet implement AI analysis, a duplicate-detection workflow, automatic Notion document creation from uploads, approval automation, approval detection, email actions, automated Run Log entries, or deployment.

## ✨ Features

### Currently available

- `GET /health` service health check
- `GET /notion/test` Notion connectivity check
- `POST /documents/test` test record creation in DOCUMENT INBOX
- `POST /documents/upload` in-memory PDF processing
- Configurable upload limit (10 MB by default)
- Rejection of empty, oversized, unsupported, corrupted, fake, and password-protected PDFs
- OCR/human-review flag for valid PDFs with no readable text

### Planned features

- Hash-based duplicate detection
- AI extraction of document metadata and recommended actions
- Automatic storage of processed uploads in Notion
- Notion Approval Queue workflow
- Automatic approval/rejection detection
- External email notifications and actions
- Automated Run Log audit trail
- Deployment

## 🛠️ Tech Stack

| Technology | Purpose |
| --- | --- |
| Python | Backend language |
| FastAPI | HTTP API and interactive Swagger UI |
| Uvicorn | ASGI server for the FastAPI application |
| Pydantic | Response schemas and configuration validation |
| python-dotenv | Loading local environment variables from `.env` |
| HTTPX | Async HTTP requests to the Notion API |
| PyMuPDF | In-memory PDF opening, verification, and text extraction |
| python-multipart | Multipart file-upload support for FastAPI |
| Notion API | Connected document, approval, and run-log database foundation |

## 📁 Project Structure

```text
docflow-ai/
├── .env.example             # Safe environment-variable template
├── .gitignore               # Prevents secrets, virtual environments, and generated files from being committed
├── README.md
├── config.py                # Environment-based configuration
├── main.py                  # FastAPI application and current endpoints
├── requirements.txt
├── models/
│   ├── __init__.py
│   └── schemas.py           # Pydantic API response models
├── services/
│   ├── __init__.py
│   ├── notion_service.py    # Notion API connection and test-record logic
│   └── pdf_service.py       # PDF processing and safe text extraction
└── utils/
    ├── __init__.py
    └── hashing.py           # SHA-256 file-hash utility
```

The real `.env` file is intentionally omitted from the repository structure because it is local and ignored by Git.

## ⚙️ Installation

Clone the repository and enter the project directory:

```powershell
git clone https://github.com/KrishBansal24/docflow-ai.git
cd docflow-ai
```

Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, allow it for the current window and activate again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Install the dependencies:

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Create a local `.env` file by copying `.env.example`, then provide your own Notion configuration:

```powershell
Copy-Item .env.example .env
```

```dotenv
NOTION_TOKEN=your_notion_token_here
DOCUMENT_INBOX_ID=your_document_inbox_database_id
APPROVAL_QUEUE_ID=your_approval_queue_database_id
RUN_LOG_ID=your_run_log_database_id
MAX_UPLOAD_SIZE_MB=10
```

`MAX_UPLOAD_SIZE_MB` is optional; the code defaults to 10 when it is absent. Never commit your real `.env` file.

Run the server:

```powershell
uvicorn main:app --reload
```

Open Swagger UI at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).

## 📡 API Endpoints

### `GET /health`

Checks that the FastAPI service is running. It does not call Notion.

```json
{
  "status": "running",
  "service": "DocFlow AI"
}
```

### `GET /notion/test`

Verifies the configured Notion token and access to DOCUMENT INBOX, APPROVAL QUEUE, and RUN LOG. On success, it returns `success`, a human-readable `message`, and a `databases` object mapping the three database names to their resolved Notion data-source IDs. A Notion or configuration failure returns a 502 response with a safe error detail.

### `POST /documents/test`

Creates a simple **DocFlow AI - Test Document** record in DOCUMENT INBOX. This is a Phase 1 connectivity test, not an automated upload-to-Notion workflow. A successful request returns HTTP 201 with:

```json
{
  "success": true,
  "message": "Test document created in DOCUMENT INBOX.",
  "page_id": "notion_page_id",
  "page_url": "https://www.notion.so/..."
}
```

### `POST /documents/upload`

Accepts a multipart form upload with one `file` field. The file must be a PDF and may not exceed the configured limit. The backend processes it entirely in memory.

Successful readable-PDF response:

```json
{
  "filename": "invoice.pdf",
  "page_count": 2,
  "text": "Extracted PDF text goes here",
  "character_count": 1540,
  "file_hash": "sha256_hash_here",
  "needs_human_review": false,
  "message": "PDF processed successfully"
}
```

A valid scanned PDF with no readable text returns HTTP 200 with `text` set to `""`, `character_count` set to `0`, and `needs_human_review` set to `true`. Empty uploads return 400; unsupported extensions or content types return 415; invalid/corrupted/password-protected PDFs return 422; files exceeding the limit return 413.

## 🧪 Testing

Use Swagger UI at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs):

1. Start the server with `uvicorn main:app --reload`.
2. Open Swagger UI in your browser.
3. Test `GET /health` with **Try it out** → **Execute**.
4. Test `GET /notion/test` after supplying valid Notion values in `.env`.
5. Test `POST /documents/test` and check that the test record appears in DOCUMENT INBOX.
6. Find `POST /documents/upload`, select **Try it out**, choose a PDF, and select **Execute**.

For Phase 2, test a readable invoice, utility bill, and vendor quotation. Also test a `.txt` file renamed to `.pdf`, an empty `.pdf`, a corrupted PDF, and a scanned/image-only PDF. The expected success and error behavior is described in the upload-endpoint section above.

## 🗺️ Development Roadmap

- ✅ **Phase 1 — Notion Integration:** Completed
- ✅ **Phase 2 — PDF Upload and Text Extraction:** Completed
- ⏳ **Phase 3 — Duplicate Detection:** Planned
- ⏳ **Phase 4 — AI Document Analysis:** Planned
- ⏳ **Phase 5 — Notion Document Workflow:** Planned
- ⏳ **Phase 6 — Human Approval Queue:** Planned
- ⏳ **Phase 7 — Automatic Approval Detection:** Planned
- ⏳ **Phase 8 — External Email Action:** Planned
- ⏳ **Phase 9 — Automated Run Log:** Planned
- ⏳ **Phase 10 — Error Handling and Recovery:** Planned
- ⏳ **Phase 11 — Deployment:** Planned

## 🎯 Final Project Goal

DocFlow AI aims to make business documents operational. Document management stores files so people can find them later. Document-to-action automation uses the contents of those files to help the business reach the correct next step.

The intended product is more than a PDF viewer, document summarizer, chatbot, or simple dashboard. It should reduce repetitive document handling while keeping people in control of important decisions through transparent recommendations, approvals, and an audit trail.

## 🔐 Security

Configuration and secrets are loaded from environment variables using `.env`; they are not hardcoded in the source code. The repository includes `.env.example` with placeholders only, while `.gitignore` excludes `.env`, environment-specific files, virtual environments, logs, uploads, and common IDE files.

Do not add Notion tokens, API keys, email passwords, or other credentials to source files, README examples, or commits.
