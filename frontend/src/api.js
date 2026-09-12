import axios from "axios";

// Keep saved work scoped to this browser without requiring an account.
const storageKey = "videomaker_workspace";
let workspace = localStorage.getItem(storageKey);
if (!workspace) {
  workspace = crypto.randomUUID();
  localStorage.setItem(storageKey, workspace);
}
const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || window.location.origin,
  headers: { "X-Workspace-ID": workspace },
});
export default api;
