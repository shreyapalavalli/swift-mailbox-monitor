window.swiftMonitorApp = {
  page: document.body.dataset.page || 'overview',
  lastKnownMetrics: null,

  initialize() {
    this.bindPageActions();
    this.bindCheckNow();
    this.refreshAll();
    window.swiftMonitorPoller.schedule();
  },

  bindPageActions() {
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') {
        this.refreshAll();
      }
    });

    const statusFilter = document.getElementById('queue-status-filter');
    const categoryFilter = document.getElementById('queue-category-filter');
    const searchInput = document.getElementById('queue-search');
    const outcomeFilter = document.getElementById('activity-outcome-filter');
    const swiftOnly = document.getElementById('activity-swift-only');

    if (statusFilter) statusFilter.addEventListener('change', () => this.renderQueuePage());
    if (categoryFilter) categoryFilter.addEventListener('change', () => this.renderQueuePage());
    if (searchInput) searchInput.addEventListener('input', () => this.renderQueuePage());
    if (outcomeFilter) outcomeFilter.addEventListener('change', () => this.renderActivityPage());
    if (swiftOnly) swiftOnly.addEventListener('change', () => this.renderActivityPage());
  },

  bindCheckNow() {
    const button = document.getElementById('check-now-btn');
    if (!button) return;
    button.addEventListener('click', async () => {
      button.disabled = true;
      button.textContent = 'Checking…';
      try {
        const result = await window.swiftMonitorApi.runProcessNow();
        const newCount = result.processed || 0;
        window.swiftMonitorAlerts.showToast(`Checked mailbox: ${newCount} processed`, 'success');
      } catch (error) {
        window.swiftMonitorAlerts.showToast(error.message || 'Could not check mailbox', 'error');
      } finally {
        button.disabled = false;
        button.textContent = 'Check now';
      }
    });
  },

  async refreshAll() {
    try {
      await Promise.all([
        this.loadMetrics(),
        this.loadQueue(),
        this.loadActivity(),
        this.checkConnection(),
      ]);
      this.renderCurrentPage();
    } catch (error) {
      const pill = document.getElementById('connection-pill');
      if (pill) {
        pill.textContent = 'Backend unreachable';
        pill.className = 'pill danger';
      }
    }
  },

  async loadMetrics() {
    try {
      const metrics = await window.swiftMonitorApi.getMetrics();
      window.swiftMonitorStore.metrics = metrics;
      if (metrics.last_processed_at) {
        window.swiftMonitorStore.lastProcessedAt = metrics.last_processed_at;
      }
    } catch (error) {
      console.warn('Metrics unavailable:', error);
    }
  },

  async loadQueue() {
    try {
      const rows = await window.swiftMonitorApi.listSwifts({ limit: 1000 });
      const normalized = Array.isArray(rows) ? rows : [];
      window.swiftMonitorStore.setRows(normalized);
      window.swiftMonitorStore.setCursor(normalized);
      if (!window.swiftMonitorStore.cursor) {
        window.swiftMonitorStore.cursor = new Date().toISOString();
      }
    } catch (error) {
      console.warn('Queue unavailable:', error);
    }
  },

  async loadActivity() {
    try {
      const items = await window.swiftMonitorApi.getActivity(50);
      window.swiftMonitorStore.activity = Array.isArray(items) ? items : [];
    } catch (error) {
      console.warn('Activity unavailable:', error);
    }
  },

  async checkConnection() {
    try {
      const user = await window.swiftMonitorApi.getConnectionStatus();
      const identity = user.userPrincipalName || user.displayName || 'Connected';
      const pill = document.getElementById('connection-pill');
      if (pill) {
        pill.textContent = `Connected as ${identity}`;
        pill.className = 'pill success';
      }
      window.swiftMonitorStore.connection = { connected: true, label: identity, details: user };
    } catch (error) {
      const pill = document.getElementById('connection-pill');
      if (pill) {
        pill.textContent = 'Mailbox not connected';
        pill.className = 'pill danger';
      }
      window.swiftMonitorStore.connection = { connected: false, label: 'Not connected', details: null };
    }

    this.renderHeaderMeta();
  },

  renderHeaderMeta() {
    const activity = document.getElementById('last-activity');
    const metrics = window.swiftMonitorStore.metrics || {};
    if (activity) {
      if (metrics.last_processed_at) {
        activity.textContent = `Last activity ${this.relativeTime(metrics.last_processed_at)}`;
      } else {
        activity.textContent = 'No activity yet';
      }
    }

    const banner = document.getElementById('dry-run-banner');
    if (banner) {
      const dryRun = window.swiftMonitorStore.activity.some((item) => item.outcome === 'DRY_RUN');
      banner.classList.toggle('hidden', !dryRun);
    }
  },

  renderCurrentPage() {
    this.renderHeaderMeta();
    switch (this.page) {
      case 'overview':
        this.renderOverviewPage();
        break;
      case 'queue':
        this.renderQueuePage();
        break;
      case 'activity':
        this.renderActivityPage();
        break;
      case 'system':
        this.renderSystemPage();
        break;
      case 'detail':
        this.renderDetailPage();
        break;
      default:
        break;
    }
  },

  renderOverviewPage() {
    const metrics = window.swiftMonitorStore.metrics || {};
    const container = document.getElementById('metrics-grid');
    if (container) {
      const tiles = [
        ['SWIFTs today', metrics.swift_today || 0],
        ['Needs action', metrics.open_action_required || 0],
        ['Priority', metrics.open_priority || 0],
        ['Auto-closed', (metrics.by_status_today && metrics.by_status_today.AUTO_CLOSED) || 0],
        ['Routed to CST', (metrics.by_status_today && metrics.by_status_today.ROUTED_CST) || 0],
        ['Auto-replied', (metrics.by_status_today && metrics.by_status_today.RESPONDED) || 0],
        ['Failures', metrics.failed_open || 0],
      ];
      container.innerHTML = tiles.map(([label, value]) => `
        <div class="metric-card">
          <div class="metric-label">${label}</div>
          <div class="metric-value">${value}</div>
        </div>
      `).join('');
    }

    const alertStrip = document.getElementById('priority-alert-strip');
    if (alertStrip) {
      const openPriorityRows = Array.from(window.swiftMonitorStore.rows.values()).filter((row) => row.status === 'PRIORITY');
      if (!openPriorityRows.length) {
        alertStrip.innerHTML = '<div class="empty-state">No priority alerts.</div>';
        return;
      }
      alertStrip.innerHTML = openPriorityRows.map((row) => `
        <button class="alert-chip" type="button" data-reference="${row.reference}">${row.reference} · ${row.message_type || 'Unknown'} · ${row.category}</button>
      `).join('');
      alertStrip.querySelectorAll('button[data-reference]').forEach((button) => {
        button.addEventListener('click', () => {
          window.location.href = `/swift/${encodeURIComponent(button.dataset.reference)}`;
        });
      });
    }

    this.renderOverviewQueue();
    this.renderActivityFeed();
  },

  renderOverviewQueue() {
    const rows = window.swiftMonitorStore.getOpenRows();
    const tableBody = document.getElementById('overview-queue-body');
    if (!tableBody) return;

    if (!rows.length) {
      tableBody.innerHTML = '<tr><td colspan="8" class="empty-state">No open items.</td></tr>';
      return;
    }

    tableBody.innerHTML = rows.slice(0, 8).map((row) => {
      const priority = row.priority === 'HIGH' ? '● High' : row.priority === 'NORMAL' ? '● Normal' : '● Low';
      const amount = window.swiftMonitorStore.formatCurrency(row.amount, row.currency);
      return `
        <tr>
          <td>${priority}</td>
          <td><a href="/swift/${encodeURIComponent(row.reference)}">${row.reference}</a></td>
          <td>${row.message_type || '—'}</td>
          <td>${row.category || '—'}</td>
          <td>${amount}</td>
          <td>${this.relativeTime(row.received_at || row.created_at)}</td>
          <td><span class="status-badge ${this.statusClass(row.status)}">${row.status}</span></td>
          <td>
            <button class="btn btn-small" data-action="start" data-reference="${row.reference}">Start</button>
          </td>
        </tr>
      `;
    }).join('');

    tableBody.querySelectorAll('[data-action="start"]').forEach((button) => {
      button.addEventListener('click', () => this.updateStatus(button.dataset.reference, 'IN_PROGRESS'));
    });
  },

  renderActivityFeed() {
    const feed = document.getElementById('activity-feed');
    if (!feed) return;
    const rows = window.swiftMonitorStore.activity.slice(0, 10);
    if (!rows.length) {
      feed.innerHTML = '<li class="empty-state">No activity yet.</li>';
      return;
    }
    feed.innerHTML = rows.map((item) => `
      <li class="activity-item ${item.outcome === 'FAILED' ? 'failed' : ''}">
        <span class="time">${this.formatTime(item.processed_at)}</span>
        <span class="status-badge ${this.statusClass(item.status || item.outcome)}">${item.status || item.outcome}</span>
        <span class="ref">${item.reference || '—'}</span>
        <span class="subject">${(item.subject || '').slice(0, 60)}</span>
      </li>
    `).join('');
  },

  renderQueuePage() {
    const tableBody = document.getElementById('queue-table-body');
    if (!tableBody) return;

    const statusFilter = document.getElementById('queue-status-filter')?.value || '';
    const categoryFilter = document.getElementById('queue-category-filter')?.value || '';
    const searchValue = (document.getElementById('queue-search')?.value || '').toLowerCase();

    let rows = Array.from(window.swiftMonitorStore.rows.values()).filter((row) => {
      const byStatus = !statusFilter || row.status === statusFilter;
      const byCategory = !categoryFilter || row.category === categoryFilter;
      const haystack = `${row.reference || ''} ${row.related_reference || ''} ${row.sender_bic || ''} ${row.business_purpose || ''}`.toLowerCase();
      const byText = !searchValue || haystack.includes(searchValue);
      return byStatus && byCategory && byText;
    });

    rows.sort((a, b) => {
      const order = { HIGH: 0, NORMAL: 1, LOW: 2 };
      return (order[a.priority] ?? 99) - (order[b.priority] ?? 99) || (a.received_at || '').localeCompare(b.received_at || '');
    });

    if (!rows.length) {
      tableBody.innerHTML = '<tr><td colspan="10" class="empty-state">No matching queue items.</td></tr>';
      return;
    }

    tableBody.innerHTML = rows.map((row) => `
      <tr>
        <td>${row.priority || 'NORMAL'}</td>
        <td><a href="/swift/${encodeURIComponent(row.reference)}">${row.reference}</a></td>
        <td>${row.message_type || '—'}</td>
        <td>${row.category || '—'}</td>
        <td>${row.sender_bic || '—'}</td>
        <td>${window.swiftMonitorStore.formatCurrency(row.amount, row.currency)}</td>
        <td>${(row.business_purpose || '').slice(0, 90)}</td>
        <td>${this.relativeTime(row.received_at || row.created_at)}</td>
        <td><span class="status-badge ${this.statusClass(row.status)}">${row.status}</span></td>
        <td>
          <button class="btn btn-small" data-action="start" data-reference="${row.reference}">Start</button>
          <button class="btn btn-small btn-primary" data-action="resolve" data-reference="${row.reference}">Resolve</button>
        </td>
      </tr>
    `).join('');

    tableBody.querySelectorAll('[data-action="start"]').forEach((button) => {
      button.addEventListener('click', () => this.updateStatus(button.dataset.reference, 'IN_PROGRESS'));
    });

    tableBody.querySelectorAll('[data-action="resolve"]').forEach((button) => {
      button.addEventListener('click', () => this.updateStatus(button.dataset.reference, 'RESOLVED'));
    });
  },

  renderActivityPage() {
    const tableBody = document.getElementById('activity-table-body');
    if (!tableBody) return;

    const outcomeValue = document.getElementById('activity-outcome-filter')?.value || '';
    const swiftOnly = document.getElementById('activity-swift-only')?.checked !== false;

    let rows = window.swiftMonitorStore.activity.filter((item) => {
      const byOutcome = !outcomeValue || item.outcome === outcomeValue;
      const bySwift = !swiftOnly || item.is_swift === 1 || item.is_swift === true;
      return byOutcome && bySwift;
    });

    if (!rows.length) {
      tableBody.innerHTML = '<tr><td colspan="8" class="empty-state">No matching activity rows.</td></tr>';
      return;
    }

    tableBody.innerHTML = rows.map((item) => `
      <tr>
        <td>${this.formatTime(item.processed_at)}</td>
        <td>${item.folder || '—'}</td>
        <td>${item.reference || '—'}</td>
        <td>${item.category || '—'}</td>
        <td>${item.action || '—'}</td>
        <td>${item.status || '—'}</td>
        <td><span class="status-badge ${this.outcomeClass(item.outcome)}">${item.outcome || '—'}</span></td>
        <td>${(item.subject || '').slice(0, 80)}</td>
      </tr>
    `).join('');
  },

  renderSystemPage() {
    const card = document.getElementById('system-status-card');
    if (!card) return;

    const connection = window.swiftMonitorStore.connection;
    const metrics = window.swiftMonitorStore.metrics || {};
    const statusText = connection.connected ? `Connected as ${connection.label}` : 'Mailbox not connected';
    const dryRun = window.swiftMonitorStore.activity.some((item) => item.outcome === 'DRY_RUN');

    card.innerHTML = `
      <div class="status-row">
        <span class="pill ${connection.connected ? 'success' : 'danger'}">${statusText}</span>
      </div>
      <div class="system-metrics">
        <div><strong>Last processed</strong><span>${metrics.last_processed_at ? this.formatTime(metrics.last_processed_at) : 'Never'}</span></div>
        <div><strong>Open action required</strong><span>${metrics.open_action_required || 0}</span></div>
        <div><strong>Open priority</strong><span>${metrics.open_priority || 0}</span></div>
      </div>
      <div class="system-note ${dryRun ? '' : 'hidden'}">Dry run is active: no mailbox changes are being applied.</div>
    `;

    const logList = document.getElementById('system-log-list');
    if (!logList) return;
    const logs = window.swiftMonitorStore.activity.slice(0, 7);
    logList.innerHTML = logs.map((item) => `
      <div class="log-item">
        <span class="time">${this.formatTime(item.processed_at)}</span>
        <span class="status-badge ${this.outcomeClass(item.outcome)}">${item.outcome}</span>
        <span>${item.reference || '—'} ${item.action ? `· ${item.action}` : ''}</span>
      </div>
    `).join('');
  },

  async renderDetailPage() {
    const reference = window.swiftMonitorDetailReference;
    if (!reference) return;
    const detailWrap = document.getElementById('detail-content');
    if (!detailWrap) return;

    try {
      const row = await window.swiftMonitorApi.getDetail(reference);
      const title = document.getElementById('detail-reference');
      const meta = document.getElementById('detail-meta');
      if (title) title.textContent = row.reference;
      if (meta) meta.textContent = `${row.message_type || 'Unknown'} · ${row.category || 'Unknown'} · ${row.status || '—'}`;

      document.getElementById('detail-start-btn')?.addEventListener('click', () => this.updateStatus(row.reference, 'IN_PROGRESS'));
      document.getElementById('detail-resolve-btn')?.addEventListener('click', () => this.updateStatus(row.reference, 'RESOLVED'));

      detailWrap.innerHTML = `
        <div class="detail-card">
          <h3>Key details</h3>
          <dl>
            <div><dt>Related reference</dt><dd>${row.related_reference || '—'}</dd></div>
            <div><dt>Sender BIC</dt><dd>${row.sender_bic || '—'}</dd></div>
            <div><dt>Receiver BIC</dt><dd>${row.receiver_bic || '—'}</dd></div>
            <div><dt>Amount</dt><dd>${window.swiftMonitorStore.formatCurrency(row.amount, row.currency)}</dd></div>
            <div><dt>Received</dt><dd>${this.formatTime(row.received_at)}</dd></div>
          </dl>
        </div>
        <div class="detail-card">
          <h3>Business purpose</h3>
          <pre>${this.escapeHtml(row.business_purpose || row.narrative || 'No business purpose available.')}</pre>
        </div>
        <div class="detail-card">
          <h3>Why this category</h3>
          <p>${this.escapeHtml(row.reason || 'No reason supplied.')}</p>
          ${(row.matched_terms || []).map((term) => `<span class="chip">${this.escapeHtml(term)}</span>`).join('') || '<p>None</p>'}
        </div>
        <div class="detail-card">
          <h3>Message text</h3>
          <pre>${this.escapeHtml(row.narrative || 'No narrative available.')}</pre>
        </div>
      `;
    } catch (error) {
      detailWrap.innerHTML = `<div class="alert-box error">Unable to load detail: ${this.escapeHtml(error.message)}</div>`;
    }
  },

  async updateStatus(reference, status) {
    try {
      const updated = await window.swiftMonitorApi.patchStatus(reference, status);
      const rows = Array.from(window.swiftMonitorStore.rows.values());
      const nextRows = rows.map((item) => item.reference === reference ? updated : item);
      window.swiftMonitorStore.setRows(nextRows);
      window.swiftMonitorAlerts.showToast(`${reference} marked as ${status}`, 'success');
      this.renderCurrentPage();
    } catch (error) {
      window.swiftMonitorAlerts.showToast(error.message || 'Update failed', 'error');
    }
  },

  statusClass(status) {
    switch (status) {
      case 'PRIORITY':
        return 'status-priority';
      case 'ACTION_REQUIRED':
        return 'status-warn';
      case 'IN_PROGRESS':
        return 'status-progress';
      case 'RESOLVED':
        return 'status-resolved';
      case 'RESPONDED':
        return 'status-info';
      default:
        return 'status-neutral';
    }
  },

  outcomeClass(outcome) {
    if (outcome === 'FAILED') return 'status-priority';
    if (outcome === 'DRY_RUN') return 'status-warn';
    return 'status-info';
  },

  relativeTime(value) {
    if (!value) return '—';
    try {
      const diffMs = Date.now() - new Date(value).getTime();
      const totalSeconds = Math.max(0, Math.floor(diffMs / 1000));
      const minutes = Math.floor(totalSeconds / 60);
      const hours = Math.floor(minutes / 60);
      const days = Math.floor(hours / 24);
      if (days > 0) return `${days}d`;
      if (hours > 0) return `${hours}h`;
      if (minutes > 0) return `${minutes}m`;
      return `${totalSeconds}s`;
    } catch (error) {
      return value;
    }
  },

  formatTime(value) {
    if (!value) return '—';
    try {
      return new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch (error) {
      return value;
    }
  },

  escapeHtml(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  },
};

window.addEventListener('DOMContentLoaded', () => {
  window.swiftMonitorApp.initialize();
});
