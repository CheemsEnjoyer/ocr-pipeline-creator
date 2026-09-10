import vinext from "vinext";
import { defineConfig } from "vite";

// Standard Node frontend. The /api route forwards requests to FastAPI.
export default defineConfig({ plugins: [vinext()] });
