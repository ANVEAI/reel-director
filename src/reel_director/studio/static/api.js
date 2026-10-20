/** Studio HTTP API client. Mirrors the contract in the studio spec exactly; no other endpoints. */

export class ApiError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.status = status;
  }
}

function errorText(status, text) {
  let msg = text;
  try {
    const body = JSON.parse(text);
    msg = body.error || body.message || text;
  } catch { /* plain-text error body: use it as is */ }
  return `${status} ${String(msg || 'request failed').slice(0, 300)}`;
}

async function request(url, opts = {}) {
  let res;
  try {
    res = await fetch(url, { cache: 'no-store', ...opts });
  } catch {
    throw new ApiError('the studio server is not reachable (is `python -m reel_director studio` still running?)');
  }
  const text = await res.text();
  if (!res.ok) throw new ApiError(errorText(res.status, text), res.status);
  try {
    return text ? JSON.parse(text) : null;
  } catch {
    throw new ApiError(`unexpected non-JSON reply from ${url}`, res.status);
  }
}

export const getProject = () => request('/api/project');
export const getBuild = () => request('/api/build');
export const startBuild = () => request('/api/build', { method: 'POST' });
/** Preview edit: takes so far + RECORD slots; reported through getBuild() like a build. */
export const startPreview = () => request('/api/preview', { method: 'POST' });
export const setPreset = (name) => request(`/api/preset?name=${encodeURIComponent(name)}`, { method: 'POST' });
/** Build toggles: {director: bool} (editing director review + fix rounds), {matte: bool} (background blur). */
export const setOptions = (opts) => request(`/api/options?${new URLSearchParams(
  Object.entries(opts).map(([k, v]) => [k, v ? '1' : '0']))}`, { method: 'POST' });
/** {profile: creator profile | null}: what `learn creator` measured on the takes so far (framing coach). */
export const getCreator = () => request('/api/creator');
/** B-roll panel: {items, credits, spend, treatments, youtube_warning, stamp, note} from <project>/media.json. */
export const getBroll = () => request('/api/broll');
/** action: "swap" | "reject" | "restore" | "treatment" | "approve"; q: {alt} or {name}. */
export const brollAction = (slot, action, q = {}) =>
  request(`/api/broll/${encodeURIComponent(slot)}/${action}?${new URLSearchParams(q)}`, { method: 'POST' });

/** action: "pin" | "unpin" | "discard" */
export const takeAction = (name, action) =>
  request(`/api/takes/${encodeURIComponent(name)}/${action}`, { method: 'POST' });

/** "raw/hook-1.mp4" -> "/media/raw/hook-1.mp4"; already-absolute media URLs pass through. */
export function mediaUrl(src) {
  if (src.startsWith('/media/')) return src;
  return '/media/' + src.split('/').map(encodeURIComponent).join('/');
}

/** JSON safe for an HTTP header. Header values must be bytes; labels such as
 *  "Alex’s iPhone Camera" (curly apostrophe) would make setRequestHeader throw. */
export function asciiJSON(obj) {
  return JSON.stringify(obj).replace(/[^\x20-\x7e]/g,
    c => '\\u' + c.charCodeAt(0).toString(16).padStart(4, '0'));
}

/** POST a take's bytes; resolves {name}. XHR rather than fetch: only XHR reports upload progress. */
export function uploadTake({ shot, source, ext, blob, info, onProgress }) {
  const q = new URLSearchParams({ shot, source, ext });
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `/api/takes?${q}`);
    xhr.setRequestHeader('Content-Type', blob.type || 'application/octet-stream');
    xhr.setRequestHeader('X-Capture-Info', asciiJSON(info));
    xhr.upload.onprogress = e => e.lengthComputable && onProgress?.(e.loaded / e.total);
    xhr.onload = () => {
      let body = null;
      try { body = JSON.parse(xhr.responseText); } catch { /* handled below */ }
      if (xhr.status >= 200 && xhr.status < 300 && body?.name) resolve(body);
      else reject(new ApiError(errorText(xhr.status, xhr.responseText), xhr.status));
    };
    xhr.onerror = () => reject(new ApiError('network error (is the studio server running?)'));
    xhr.onabort = () => reject(new ApiError('upload aborted'));
    xhr.send(blob);
  });
}
