/**
 * Pre-configured Axios instance.
 * Automatically injects the JWT Authorization header.
 */

import axios from "axios";
import { getToken, clearAuth } from "@/app/store";

const api = axios.create({
  baseURL: "/api",
  headers: { "Content-Type": "application/json" },
});

// Request interceptor — attach token
api.interceptors.request.use((config) => {
  const token = getToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Response interceptor — handle 401 (redirect to login), surface 403 properly
api.interceptors.response.use(
  (response) => response,
  (error) => {
    // A failed login is also a 401; let the login page show the error instead of reloading
    const isLoginRequest = error.config?.url === "/users/login";
    if (error.response?.status === 401 && !isLoginRequest) {
      clearAuth();
      window.location.href = "/login";
    }
    return Promise.reject(error);
  },
);

export default api;
