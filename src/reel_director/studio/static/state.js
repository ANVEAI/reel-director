/** Shared studio state for this tab, plus lookups over the latest /api/project snapshot. */
import { loadPrefs } from './devices.js';

export const S = {
  project: null,        // last /api/project reply
  shot: null,           // selected shot id
  rec: 'idle',          // "idle" | "countdown" | "recording" | "stopping"
  recorder: null,
  recShot: null,        // shot the take in progress belongs to
  cams: [], mics: [],   // MediaDeviceInfo lists (Desk View and Chrome's alias entries removed)
  cam: null, camDev: null, mic: null, micDev: null,
  mime: null, vbps: 0,  // chosen MediaRecorder format and video bitrate
  uploads: [],          // takes in flight or failed (bytes kept for Retry / Save)
  expanded: new Set(),  // take names with their QA report open
  playing: null,        // take name in the inline player
  lastTake: null,       // newest take recorded in this tab (auto-advance follows it)
  build: null,          // last build status
  prefs: { mirror: true, autoAdvance: true, ...(loadPrefs().ui || {}) },
};

export const shotById = id => S.project?.shots.find(s => s.id === id);
export const allTakes = () => (S.project?.shots || []).flatMap(s => s.takes || []);
