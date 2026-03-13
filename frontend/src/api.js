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
  bulkDeleteJobs: (jobIds) => request('/jobs/bulk-delete', { method: 'POST', body: JSON.stringify({ job_ids: jobIds }) }),
  updateNotes: (jobId, notes) => request(`/jobs/${jobId}/notes`, { method: 'PUT', body: JSON.stringify({ notes }) }),

  // RFMS Upload (supports multiple files)
  uploadRFMS: (jobId, files) => {
    const form = new FormData();
    const fileList = Array.isArray(files) ? files : [files];
    fileList.forEach(f => form.append('files', f));
    return fetch(`${BASE}/jobs/${jobId}/upload-rfms`, { method: 'POST', body: form })
      .then(r => { if (!r.ok) throw new Error('Upload failed'); return r.json(); });
  },

  // Quote Upload
  uploadQuotes: (jobId, files) => {
    const form = new FormData();
    files.forEach(f => form.append('files', f));
    return fetch(`${BASE}/jobs/${jobId}/upload-quotes`, { method: 'POST', body: form })
      .then(r => { if (!r.ok) throw new Error('Upload failed'); return r.json(); });
  },

  // Materials
  updateMaterials: (jobId, materials) =>
    request(`/jobs/${jobId}/materials`, { method: 'PUT', body: JSON.stringify({ materials }) }),

  // Calculate
  calculate: (jobId) => request(`/jobs/${jobId}/calculate`, { method: 'POST' }),

  // Bid
  generateBid: (jobId) => request(`/jobs/${jobId}/generate-bid`, { method: 'POST' }),
  getBidPdfUrl: (jobId) => `${BASE}/jobs/${jobId}/bid.pdf`,

  // Labor catalog
  uploadLaborCatalog: (file) => {
    const form = new FormData();
    form.append('file', file);
    return fetch(`${BASE}/labor-catalog/upload`, { method: 'POST', body: form })
      .then(r => { if (!r.ok) throw new Error('Upload failed'); return r.json(); });
  },

  // Settings
  getSettings: () => request('/settings'),
  updateSettings: (data) => request('/settings', { method: 'POST', body: JSON.stringify(data) }),
};
