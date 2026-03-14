const BASE = '/api';

async function request(url, options = {}) {
  const res = await fetch(`${BASE}${url}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Request failed');
  }
  return res.json();
}

export const api = {
  // Jobs
  listJobs: () => request('/jobs'),
  createJob: (data) => request('/jobs', { method: 'POST', body: JSON.stringify(data) }),
  getJob: (id) => request(`/jobs/${id}`),
  deleteJob: (id) => request(`/jobs/${id}`, { method: 'DELETE' }),
  duplicateJob: (jobId) => request('/jobs/' + jobId + '/duplicate', { method: 'POST' }),
  bulkDeleteJobs: (jobIds) => request('/jobs/bulk-delete', { method: 'POST', body: JSON.stringify({ job_ids: jobIds }) }),
  updateNotes: (jobId, notes) => request(`/jobs/${jobId}/notes`, { method: 'PUT', body: JSON.stringify({ notes }) }),

  // RFMS Upload (supports multiple files)
  uploadRFMS: async (jobId, files) => {
    const form = new FormData();
    const fileList = Array.isArray(files) ? files : [files];
    const validFiles = fileList.filter(f => f && f.size > 0);
    console.log('[uploadRFMS] input files:', files, 'valid:', validFiles.length, validFiles.map(f => `${f.name} (${f.size}b)`));
    if (validFiles.length === 0) throw new Error('No valid files selected');
    validFiles.forEach(f => form.append('files', f));
    const r = await fetch(`${BASE}/jobs/${jobId}/upload-rfms`, { method: 'POST', body: form });
    if (!r.ok) {
      const text = await r.text();
      console.error('[uploadRFMS] error:', r.status, text);
      let msg;
      try { const err = JSON.parse(text); msg = typeof err.detail === 'string' ? err.detail : JSON.stringify(err.detail); } catch { msg = text; }
      throw new Error(msg || 'Upload failed');
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
    const r = await fetch(`${BASE}/jobs/${jobId}/upload-quotes`, { method: 'POST', body: form });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      const msg = typeof err.detail === 'string' ? err.detail : JSON.stringify(err.detail);
      throw new Error(msg || 'Upload failed');
    }
    return r.json();
  },

  // Materials
  updateMaterials: (jobId, materials) =>
    request(`/jobs/${jobId}/materials`, { method: 'PUT', body: JSON.stringify({ materials }) }),

  // Calculate
  calculate: (jobId) => request(`/jobs/${jobId}/calculate`, { method: 'POST' }),

  // Bid
  generateBid: (jobId) => request(`/jobs/${jobId}/generate-bid`, { method: 'POST' }),
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
    return fetch(`${BASE}/labor-catalog/upload`, { method: 'POST', body: form })
      .then(r => { if (!r.ok) throw new Error('Upload failed'); return r.json(); });
  },

  // Quotes
  clearQuotes: (jobId) => request('/jobs/' + jobId + '/quotes', { method: 'DELETE' }),

  // Jobs (update)
  updateJob: (jobId, data) => request('/jobs/' + jobId, { method: 'PUT', body: JSON.stringify(data) }),

  // Search
  search: (q) => request('/search?q=' + encodeURIComponent(q)),

  // Settings
  getSettings: () => request('/settings'),
  updateSettings: (data) => request('/settings', { method: 'POST', body: JSON.stringify(data) }),
};
