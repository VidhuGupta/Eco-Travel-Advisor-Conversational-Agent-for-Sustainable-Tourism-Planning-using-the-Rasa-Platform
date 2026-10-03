# Terra advisor frontend

React + Vite advisor dashboard for the Eco-Travel AI Advisor. It uses Rasa's REST webhook for conversation messages.

## Start locally (PowerShell)

Open four terminals in the project root. The active Python environment is `.venv`.

**Terminal 1 — Rasa server**

```powershell
.\.venv\Scripts\Activate.ps1
rasa run --enable-api --cors "*" --credentials credentials.yml --port 5005
```

**Terminal 2 — custom actions**

```powershell
.\.venv\Scripts\Activate.ps1
rasa run actions --port 5055
```

**Terminal 3 — React frontend**

```powershell
cd frontend
npm install
npm run dev
```

**Terminal 4 — admin analytics API**

```powershell
.\.venv\Scripts\python.exe admin_server.py
```

Open the local address printed by Vite (usually `http://127.0.0.1:5173`). The frontend defaults to `http://localhost:5005/webhooks/rest/webhook`; the gear button lets you change the endpoint.

Open `/admin` on the same local Vite origin for the protected analytics dashboard. It reads aggregate counts from the local `conversation.db`; it does not return transcripts. Keep the admin API bound to loopback and do not expose port 8060 publicly.

The action server uses server-side keys in the root `.env`: Duffel for flight and stay searches, Climatiq for route emissions, OpenCage for accommodation coordinates, and Travelpayouts for cached fare comparisons. Travelpayouts prices are historical/cached indications, not live availability. Local experiences remain clearly marked sample data because these providers do not provide an activities catalog. API credentials and admin login configuration must never be put in frontend variables or committed.
