import {api} from "./client.js";
export const listProjects = () => api("/projects");
export const createProject = name => api("/projects", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({name})});
