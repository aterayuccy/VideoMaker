import axios from "axios";

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || window.location.origin,
});
export default api;
