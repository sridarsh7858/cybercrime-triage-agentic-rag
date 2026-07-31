// Base URL of the FastAPI backend. Override via a .env file (VITE_API_URL=...).
export const API_BASE_URL =
  import.meta.env.VITE_API_URL?.replace(/\/$/, "") || "http://localhost:8000";
