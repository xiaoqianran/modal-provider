/** Backward-compatible facade. */
export {BASE, api, errorMessage} from "./client.js";
export {TEXT_IMAGE, IMAGE_3D, listCapabilities3d, capabilities, health3d, listModels3d, listOperations3d} from "./capabilities.js";
export {listAssets, uploadAsset3d, assetContentUrl} from "./assets.js";
export {listProjects, createProject} from "./projects.js";
export {terminal, listJobs, submitJob, submitOperation3d, submitImageTo3d, jobArtifactRef, getJob3d, cancelJob, fetchArtifactBlob3d, pollJob3d, generateImage2d} from "./jobs.js";
