import { localToday } from './bidTracker';

const BASE = '/api';

// App.jsx registers this so any "not logged in" (401) reply brings up the login screen.
let authRequiredHandler = null;
export function setAuthRequiredHandler(handler) {
  authRequiredHandler = handler;
}

// fetch() for our own API: sends the login cookie and reports a lost session.
// Returns the Response as-is so callers keep their own error handling.
export async function apiFetch(input, init = {}) {
  const res = await fetch(input, { credentials: 'same-origin', ...init });
  if (res.status === 401 && authRequiredHandler) authRequiredHandler();
  return res;
}

// Thrown when the server answers with an error. The message is the text to show;
// .status is the HTTP status (409 = someone else changed it, 404 = not found),
// .detail is the server's "detail" value and .body the whole reply.
export class ApiError extends Error {
  constructor(message, { status = 0, detail = null, body = null } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
    this.body = body;
  }
}

async function request(url, options = {}) {
  const res = await apiFetch(`${BASE}${url}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    const detail = body?.detail ?? null;
    throw new ApiError(detail || 'Request failed', { status: res.status, detail, body });
  }
  return res.json();
}

const AUDIT_FILTER_KEYS = ['job_id', 'entity_type', 'entity_id', 'actor', 'action', 'since', 'until', 'q', 'before_id', 'limit'];

// "?actor=josh&since=..." from a filters object; blank filters are left out.
function auditQuery(filters = {}) {
  const params = new URLSearchParams();
  for (const key of AUDIT_FILTER_KEYS) {
    const value = filters[key];
    if (value === null || value === undefined) continue;
    const text = String(value).trim();
    if (text !== '') params.set(key, text);
  }
  const qs = params.toString();
  return qs ? '?' + qs : '';
}

// Login calls expect 401 as a normal answer, so they skip the login-screen trigger.
async function authRequest(url, options = {}) {
  const res = await fetch(`${BASE}${url}`, {
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data?.detail ?? null;
    throw new ApiError(typeof detail === 'string' ? detail : 'Request failed', { status: res.status, detail, body: data });
  }
  return data;
}

export const api = {
  // Sign-in
  getCurrentUser: async () => {
    try {
      return await authRequest('/auth/me');
    } catch (err) {
      if (err.status === 401) return null;
      throw err;
    }
  },
  login: (username, pin) => authRequest('/auth/login', { method: 'POST', body: JSON.stringify({ username, pin }) }),
  logout: () => authRequest('/auth/logout', { method: 'POST' }),
  getOnlineUsers: () => request('/auth/online'),

  // People (admins only)
  listPeople: () => request('/admin/users'),
  addPerson: (data) => request('/admin/users', { method: 'POST', body: JSON.stringify(data) }),
  updatePerson: (username, data) =>
    request('/admin/users/' + encodeURIComponent(username), { method: 'PATCH', body: JSON.stringify(data) }),
  removePerson: (username) => request('/admin/users/' + encodeURIComponent(username) + '/remove', { method: 'POST' }),
  restorePerson: (username) => request('/admin/users/' + encodeURIComponent(username) + '/restore', { method: 'POST' }),
  resetPersonPin: (username, pin) =>
    request('/admin/users/' + encodeURIComponent(username) + '/reset-pin', { method: 'POST', body: JSON.stringify({ pin }) }),
  getPeopleLog: () => request('/admin/log'),

  // Jobs
  listJobs: () => request('/jobs'),
  createJob: (data) => request('/jobs', { method: 'POST', body: JSON.stringify(data) }),
  // includeDeleted: also return a deleted bid (read-only, with deleted_at / deleted_by /
  // delete_reason) instead of "not found". Used when opening a deleted bid from a link.
  getJob: (id, { includeDeleted = false } = {}) => request(`/jobs/${id}` + (includeDeleted ? '?include_deleted=1' : '')),
  getJobReadiness: (id) => request(`/jobs/${id}/readiness`),
  getBuildInfo: () => request('/system/build'),
  getVendorIngestionHealth: () => request('/system/vendor-ingestion'),
  // Deleting only hides the bid (it moves to Deleted bids); an admin can restore it.
  // reason is required (1-500 characters).
  deleteJob: (id, reason) => request(`/jobs/${id}`, { method: 'DELETE', body: JSON.stringify({ reason }) }),
  duplicateJob: (jobId) => request('/jobs/' + jobId + '/duplicate', { method: 'POST' }),
  bulkDeleteJobs: (jobIds, reason) =>
    request('/jobs/bulk-delete', { method: 'POST', body: JSON.stringify({ ids: jobIds, job_ids: jobIds, reason }) }),
  // Deleted bids: [{ id, slug, project_name, gc_name, deleted_at, deleted_by, delete_reason, grand_total }]
  listDeletedJobs: () => request('/jobs/deleted'),
  // Admins only. Returns the restored job.
  restoreJob: (id) => request(`/jobs/${encodeURIComponent(id)}/restore`, { method: 'POST' }),
  updateNotes: (jobId, notes) => request(`/jobs/${jobId}/notes`, { method: 'PUT', body: JSON.stringify({ notes }) }),

  // RFMS Upload (supports multiple files)
  uploadRFMS: async (jobId, files) => {
    const form = new FormData();
    const fileList = Array.isArray(files) ? files : [files];
    const validFiles = fileList.filter(f => f && f.size > 0);
    console.log('[uploadRFMS] input files:', files, 'valid:', validFiles.length, validFiles.map(f => `${f.name} (${f.size}b)`));
    if (validFiles.length === 0) throw new Error('No valid files selected');
    validFiles.forEach(f => form.append('files', f));
    const r = await apiFetch(`${BASE}/jobs/${jobId}/upload-rfms`, { method: 'POST', body: form });
    if (!r.ok) {
      const text = await r.text();
      console.error('[uploadRFMS] error:', r.status, text);
      let msg;
      let body = null;
      try { body = JSON.parse(text); msg = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail); } catch { msg = text; }
      throw new ApiError(msg || 'Upload failed', { status: r.status, detail: body?.detail ?? null, body });
    }
    return r.json();
  },

  // Quote Upload
  uploadQuotes: async (jobId, files) => {
    const form = new FormData();
    const fileList = Array.isArray(files) ? files : [files];
    const validFiles = fileList.filter(f => f instanceof File && f.size > 0);
    if (validFiles.length === 0) throw new Error('No valid files selected');
    validFiles.forEach(f => form.append('files', f));
    const r = await apiFetch(`${BASE}/jobs/${jobId}/upload-quotes`, { method: 'POST', body: form });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      const msg = typeof err.detail === 'string' ? err.detail : JSON.stringify(err.detail);
      throw new ApiError(msg || 'Upload failed', { status: r.status, detail: err?.detail ?? null, body: err });
    }
    return r.json();
  },

  // Materials
  updateMaterials: (jobId, materials, baseSourceFingerprint = null, deletionReasons = {}) =>
    request(`/jobs/${jobId}/materials`, {
      method: 'PUT',
      body: JSON.stringify({
        materials,
        base_source_fingerprint: baseSourceFingerprint,
        deletion_reasons: deletionReasons,
      }),
    }),
  getMaterialPriceDecisions: (jobId) => request(`/jobs/${jobId}/price-decisions`),
  resolveVendorPriceConflict: (jobId, materialId, data) =>
    request(`/jobs/${jobId}/materials/${materialId}/quote-conflict`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // Proposal Bundles (auto-save)
  loadProposalBundles: (jobId) => request(`/jobs/${jobId}/proposal/bundles`),
  saveProposalBundles: (jobId, data) =>
    request(`/jobs/${jobId}/proposal/bundles`, { method: 'PUT', body: JSON.stringify(data) }),

  // Proposal versions: saved copies of the proposal, newest first.
  // [{ id, version_no, created_at, created_by, contributors, reason, label, grand_total,
  //    bundle_count, artifact_id, restored_from_version_id }]
  listProposalVersions: (jobId) => request(`/jobs/${jobId}/proposal/versions`),
  // One version with its proposal_data and job_fields.
  getProposalVersion: (jobId, versionId) =>
    request(`/jobs/${jobId}/proposal/versions/${encodeURIComponent(versionId)}`),
  // against: 'current' or another version id. { changes, summary }
  diffProposalVersion: (jobId, versionId, against = 'current') =>
    request(`/jobs/${jobId}/proposal/versions/${encodeURIComponent(versionId)}/diff?against=${encodeURIComponent(against)}`),
  renameProposalVersion: (jobId, versionId, label) =>
    request(`/jobs/${jobId}/proposal/versions/${encodeURIComponent(versionId)}`, { method: 'PATCH', body: JSON.stringify({ label }) }),
  // Saves the current proposal as a version first, then puts this one back. { job, version }
  restoreProposalVersion: (jobId, versionId) =>
    request(`/jobs/${jobId}/proposal/versions/${encodeURIComponent(versionId)}/restore`, { method: 'POST' }),

  // Past PDFs (every PDF ever made is kept). kind: 'proposal_pdf' | 'bid_pdf'.
  // [{ id, kind, created_at, created_by, grand_total, proposal_version_id, sha256, size }], newest first
  listJobArtifacts: (jobId, kind) =>
    request(`/jobs/${jobId}/artifacts` + (kind ? '?kind=' + encodeURIComponent(kind) : '')),
  jobArtifactDownloadUrl: (jobId, artifactId) =>
    `${BASE}/jobs/${jobId}/artifacts/${encodeURIComponent(artifactId)}/download`,

  // Rules registry / audit traces
  listRules: (params = {}) => {
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, value]) => value != null && value !== '' && value !== 'all')
    ).toString()
    return request('/rules' + (qs ? '?' + qs : ''))
  },
  getRule: (ruleId) => request('/rules/' + encodeURIComponent(ruleId)),
  getRuleVersions: (ruleId) => request('/rules/' + encodeURIComponent(ruleId) + '/versions'),
  createRule: (data) =>
    request('/rules', { method: 'POST', body: JSON.stringify(data) }),
  draftRuleFromLesson: (data) =>
    request('/rules/draft-from-lesson', { method: 'POST', body: JSON.stringify(data) }),
  listRulesets: (params = {}) => {
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, value]) => value != null && value !== '')
    ).toString()
    return request('/rulesets' + (qs ? '?' + qs : ''))
  },
  getRuleset: (version) => request('/rulesets/' + encodeURIComponent(version)),
  rollbackRuleset: (version, data = {}) =>
    request('/rulesets/' + encodeURIComponent(version) + '/rollback', { method: 'POST', body: JSON.stringify(data) }),
  updateRule: (ruleId, data) =>
    request('/rules/' + encodeURIComponent(ruleId), { method: 'PUT', body: JSON.stringify(data) }),
  archiveRule: (ruleId, data = {}) =>
    request('/rules/' + encodeURIComponent(ruleId) + '/archive', { method: 'POST', body: JSON.stringify(data) }),
  deleteRule: (ruleId) => request('/rules/' + encodeURIComponent(ruleId), { method: 'DELETE' }),
  getJobAuditTrace: (jobId) => request(`/jobs/${jobId}/audit?scope=proposal`),
  runRulesAuditHarness: (payload) =>
    request('/rules/audit-harness', { method: 'POST', body: JSON.stringify(payload) }),
  getReproducibility: (jobId) => request(`/jobs/${jobId}/reproducibility`),
  captureGoldenBaseline: (jobId, data) =>
    request(`/jobs/${jobId}/reproducibility/baseline`, { method: 'POST', body: JSON.stringify(data) }),
  runGoldenReplay: (jobId, mode = 'baseline') =>
    request(`/jobs/${jobId}/reproducibility/replay`, { method: 'POST', body: JSON.stringify({ mode }) }),
  getGoldenReplay: (replayId) => request('/reproducibility/replays/' + replayId),

  // Calculate
  calculate: (jobId) => request(`/jobs/${jobId}/calculate`, { method: 'POST' }),

  // Bid
  generateBid: (jobId) => request(`/jobs/${jobId}/generate-bid`, { method: 'POST' }),
  clearBid: (jobId) => request(`/jobs/${jobId}/bid`, { method: 'DELETE' }),
  getBidPdfUrl: (jobId) => `${BASE}/jobs/${jobId}/bid.pdf`,

  // Exclusions
  getExclusions: (jobId) => request(`/jobs/${jobId}/exclusions`),
  updateExclusions: (jobId, exclusions) =>
    request(`/jobs/${jobId}/exclusions`, { method: 'PUT', body: JSON.stringify({ exclusions }) }),

  // Materials export
  exportMaterialsCsvUrl: (jobId) => `${BASE}/jobs/${jobId}/materials/export`,

  // Labor catalog
  getLaborCatalog: () => request('/labor-catalog'),
  uploadLaborCatalog: (file) => {
    const form = new FormData();
    form.append('file', file);
    return apiFetch(`${BASE}/labor-catalog/upload`, { method: 'POST', body: form })
      .then(r => { if (!r.ok) throw new Error('Upload failed'); return r.json(); });
  },
  updateLaborCatalogEntry: (id, data) => request('/labor-catalog/' + id, { method: 'PUT', body: JSON.stringify(data) }),
  deleteLaborCatalogEntry: (id) => request('/labor-catalog/' + id, { method: 'DELETE' }),
  clearLaborCatalog: () => request('/labor-catalog', { method: 'DELETE' }),
  getStairLabor: () => request('/labor-catalog/stairs'),
  getStairSundryKits: () => request('/stair-sundry-kits'),

  // Quotes
  clearQuotes: (jobId) => request('/jobs/' + jobId + '/quotes', { method: 'DELETE' }),
  updateQuote: (quoteId, data) => request('/quotes/' + quoteId, { method: 'PUT', body: JSON.stringify(data) }),

  // Jobs (update)
  updateJob: (jobId, data) => request('/jobs/' + jobId, { method: 'PUT', body: JSON.stringify(data) }),

  // Search
  search: (q) => request('/search?q=' + encodeURIComponent(q)),

  // Company Rates
  getCompanyRates: () => request('/company-rates'),
  getCompanyRate: (type) => request('/company-rates/' + type),
  updateCompanyRate: (type, data) => request('/company-rates/' + type, { method: 'PUT', body: JSON.stringify({ data }) }),

  // Price List
  getPriceList: () => request('/price-list'),
  addPriceListEntry: (entry) => request('/price-list', { method: 'POST', body: JSON.stringify(entry) }),
  updatePriceListEntry: (id, entry) => request('/price-list/' + id, { method: 'PUT', body: JSON.stringify(entry) }),
  deletePriceListEntry: (id) => request('/price-list/' + id, { method: 'DELETE' }),
  uploadPriceList: (file) => {
    const form = new FormData();
    form.append('file', file);
    return apiFetch(`${BASE}/price-list/upload`, { method: 'POST', body: form })
      .then(r => { if (!r.ok) throw new Error('Upload failed'); return r.json(); });
  },
  clearPriceList: () => request('/price-list', { method: 'DELETE' }),

  // Settings
  getSettings: () => request('/settings'),
  updateSettings: (data) => request('/settings', { method: 'POST', body: JSON.stringify(data) }),
  testAi: (model) => request('/settings/test-ai', { method: 'POST', body: JSON.stringify({ model }) }),

  // Vendors
  listVendors: () => request('/vendors'),
  getVendor: (id) => request('/vendors/' + id),
  createVendor: (data) => request('/vendors', { method: 'POST', body: JSON.stringify(data) }),
  updateVendor: (id, data) => request('/vendors/' + id, { method: 'PUT', body: JSON.stringify(data) }),
  deleteVendor: (id) => request('/vendors/' + id, { method: 'DELETE' }),
  suggestVendorContacts: (vendorNames) => request('/vendors/suggest-contacts', { method: 'POST', body: JSON.stringify({ vendor_names: vendorNames }) }),

  // Vendor Prices / History
  searchVendorPrices: (params = {}) => {
    const qs = new URLSearchParams(params).toString()
    return request('/vendor-prices' + (qs ? '?' + qs : ''))
  },
  importVendorPrices: (file) => {
    const form = new FormData();
    form.append('file', file);
    return apiFetch(`${BASE}/vendor-prices/import`, { method: 'POST', body: form })
      .then(r => { if (!r.ok) throw new Error('Import failed'); return r.json(); });
  },
  getPriceHistory: (params = {}) => {
    const qs = new URLSearchParams(params).toString()
    return request('/materials/price-history' + (qs ? '?' + qs : ''))
  },

  // Notifications
  getNotifications: (unreadOnly = true) => request('/notifications?unread_only=' + unreadOnly),
  markNotificationRead: (id) => request('/notifications/' + id + '/read', { method: 'PUT' }),

  // AI Price Estimation
  // By the line's id, so a line added or removed by someone else can't shift which line gets priced.
  // 409 = someone changed that line's price meanwhile (their change is kept).
  estimatePrice: (jobId, materialId) => request(`/jobs/${jobId}/materials/by-id/${encodeURIComponent(materialId)}/estimate-price`, { method: 'POST' }),

  // Quote Requests
  listQuoteRequests: (jobId) => request('/jobs/' + jobId + '/quote-requests'),
  createQuoteRequest: (jobId, data) => request('/jobs/' + jobId + '/quote-requests', { method: 'POST', body: JSON.stringify(data) }),
  updateQuoteRequest: (id, data) => request('/quote-requests/' + id, { method: 'PUT', body: JSON.stringify(data) }),
  deleteQuoteRequest: (id) => request('/quote-requests/' + id, { method: 'DELETE' }),

  // Vendor Quote Test Mode / Simulation
  simStatus: () => request('/sim/status'),
  sendQuoteEmail: (jobId, data) => request('/jobs/' + jobId + '/send-quote-email', { method: 'POST', body: JSON.stringify(data) }),

  // Dropbox Scanner
  matchDropboxFolder: (jobId, folderNames) => request('/jobs/' + jobId + '/match-dropbox-folder', { method: 'POST', body: JSON.stringify({ folder_names: folderNames }) }),

  // AI: Vendor Detection & Quote Text
  detectVendors: (jobId) => request('/jobs/' + jobId + '/detect-vendors', { method: 'POST' }),
  suggestVendors: (jobId, materialIndices) => request('/jobs/' + jobId + '/suggest-vendors', { method: 'POST', body: JSON.stringify({ material_indices: materialIndices }) }),
  generateQuoteText: (jobId, data) => request('/jobs/' + jobId + '/generate-quote-text', { method: 'POST', body: JSON.stringify(data) }),

  // Activity Log & Comments
  getActivity: (jobId) => request('/jobs/' + jobId + '/activity'),
  // Comments of a deleted bid can still be read (posting is closed).
  getComments: (jobId) => request('/jobs/' + jobId + '/comments?include_deleted=1'),
  addComment: (jobId, text) => request('/jobs/' + jobId + '/comments', { method: 'POST', body: JSON.stringify({ text }) }),

  // History (audit trail): who changed what, for everything. Open to everyone logged in.
  // Filters: job_id, entity_type, entity_id, actor, action, since, until, q; paging:
  // before_id (the last reply's next_before_id) and limit. Replies: { items, next_before_id }.
  getAudit: (filters = {}) => request('/audit' + auditQuery(filters)),
  getAuditItem: (id) => request('/audit/' + encodeURIComponent(id)),
  getJobHistory: (jobId, filters = {}) => {
    const { job_id: _ignored, ...rest } = filters;
    return request('/jobs/' + encodeURIComponent(jobId) + '/history' + auditQuery(rest));
  },
  auditExportUrl: (filters = {}) => {
    const { before_id: _before, limit: _limit, ...rest } = filters;
    return `${BASE}/audit/export.csv` + auditQuery(rest);
  },

  // Bid Tracker. "today" is the browser's date so due/overdue match the person's calendar.
  getBidTracker: () => request('/bid-tracker?today=' + localToday()),
  getBidTracking: (jobId) => request(`/jobs/${jobId}/bid-tracking?today=` + localToday()),
  updateBidTracking: (jobId, data) => request(`/jobs/${jobId}/bid-tracking`, { method: 'PATCH', body: JSON.stringify({ ...data, today: localToday() }) }),
  addBidEvent: (jobId, data) => request(`/jobs/${jobId}/bid-events`, { method: 'POST', body: JSON.stringify({ ...data, today: localToday() }) }),
  getBidEvents: (jobId) => request(`/jobs/${jobId}/bid-events`),
};
