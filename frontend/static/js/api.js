window.swiftMonitorApi = {
  async request(path, options = {}) {
    const url = `${window.SWIFT_API_BASE}${path}`;
    const response = await fetch(url, {
      headers: { Accept: 'application/json', ...(options.headers || {}) },
      ...options,
    });

    const text = await response.text();
    const payload = text ? JSON.parse(text) : null;

    if (!response.ok) {
      const message = payload && payload.detail ? payload.detail : 'Request failed';
      throw new Error(message);
    }

    return payload;
  },

  async get(path, params = {}) {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') {
        query.append(key, String(value));
      }
    });
    const suffix = query.toString() ? `?${query.toString()}` : '';
    return this.request(`${path}${suffix}`);
  },

  listSwifts(params = {}) {
    return this.get('/api/swifts', params);
  },

  getMetrics() {
    return this.get('/api/swifts/metrics');
  },

  getAlerts(since = null) {
    return this.get('/api/swifts/alerts', since ? { since } : {});
  },

  getActivity(limit = 50) {
    return this.get('/api/process/log', { limit });
  },

  getConnectionStatus() {
    return this.request('/api/graph/test-user');
  },

  runProcessNow() {
    return this.request('/api/process/run', { method: 'POST' });
  },

  getDetail(reference) {
    return this.get(`/api/swifts/${encodeURIComponent(reference)}`);
  },

  patchStatus(reference, status) {
    return this.request(`/api/swifts/${encodeURIComponent(reference)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status }),
    });
  },
};
