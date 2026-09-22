import axios, { AxiosError } from 'axios';

const BQL_TOKEN = process.env.BQL_TOKEN || 'tapetide-secret-token';
const BASE_URL = 'http://127.0.0.1:8000/v1';

export const apiClient = axios.create({
  baseURL: BASE_URL,
  headers: {
    Authorization: `Bearer ${BQL_TOKEN}`
  }
});

export interface ApiError {
  error_code: number;
  message: string;
  suggestion: string;
}

export function handleApiError(error: unknown): ApiError {
  if (axios.isAxiosError(error)) {
    const status = error.response?.status || 500;
    const data = error.response?.data as any;
    
    // Explicit 503 handling from Tapetide backend
    if (status === 503) {
      return {
        error_code: 503,
        message: data?.detail || "Service unavailable",
        suggestion: "This endpoint relies on a quarantined historical data source (e.g. FII/DII). Use an alternative or remove the condition."
      };
    }
    
    return {
      error_code: status,
      message: data?.detail || error.message,
      suggestion: "Check your request parameters and ensure the API server is running at http://127.0.0.1:8000."
    };
  }
  
  return {
    error_code: 500,
    message: String(error),
    suggestion: "Internal MCP or unknown connection error."
  };
}
