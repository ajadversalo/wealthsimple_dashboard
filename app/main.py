from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import router as api_router

from dotenv import load_dotenv

# Load env variables before anything else imports
load_dotenv()

app = FastAPI(title="Options Dashboard API", version="1.0.0")

# Enable CORS so your local React/Vue frontend can fetch data without blocking
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")