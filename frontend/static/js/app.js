window.swiftMonitorApp = {
  page: document.body.dataset.page || 'overview',
  lastKnownMetrics: null,
  CONNECTION_CHECK_MS: 60000, // each check calls Microsoft Graph; don't do it on every poll
  lastConnectionCheck: 0,
  queueLoaded: false,

  initialize() {
    this.bindPageActions();
    this.bindCheckNow();
    window.swiftMonitorPoller.schedule();
  },

  bindPageActions() {
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') {
        window.swiftMonitorPoller.pollNow();
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
        this.refreshAll({ forceConnectionCheck: true });
        button.disabled = false;
        button.textContent = 'Check mailbox now';
      }
    });
  },

  /** Refresh everything; resolves to false when the backend is unreachable (the poller backs off). */
  async refreshAll({ forceConnectionCheck = false } = {}) {
    try {
      const dueForCheck = forceConnectionCheck || Date.now() - this.lastConnectionCheck >= this.CONNECTION_CHECK_MS;
      const [metricsOk] = await Promise.all([
        this.loadMetrics(),
        this.loadQueue(),
        this.loadActivity(),
        dueForCheck ? this.checkConnection() : Promise.resolve(),
      ]);
      if (!metricsOk) {
        this.showBackendUnreachable();
        return false;
      }
      this.renderCurrentPage();
      return true;
    } catch (error) {
      this.showBackendUnreachable();
      return false;
    }
  },

  showBackendUnreachable() {
    const pill = document.getElementById('connection-pill');
    this.setPill('danger', 'Backend unreachable');
    this.lastConnectionCheck = 0; // re-check the mailbox connection as soon as the backend is back
  },

  setPill(tone, text) {
    const pill = document.getElementById('connection-pill');
    if (!pill) return;
    pill.className = `pill ${tone}`;
    pill.innerHTML = `<i class="dot"></i><span>${this.esc(text)}</span>`;
  },

  /** Header date picker: show only items received/processed on that local date (null = all). */
  setDate(value) {
    window.swiftMonitorStore.selectedDate = value;
    const picker = document.getElementById('datePick');
    if (picker) picker.value = value || '';
    const button = document.getElementById('dateSelect');
    if (button) {
      button.classList.toggle('on', Boolean(value));
      button.querySelector('span').textContent = value ? this.formatDate(value) : 'Date';
    }
    const note = document.getElementById('date-note');
    if (note) {
      note.classList.toggle('hidden', !value);
      note.innerHTML = value
        ? `Showing items from <strong>${this.esc(this.formatDate(value))}</strong> · <button type="button" id="date-clear">Show all</button>`
        : '';
      const clear = document.getElementById('date-clear');
      if (clear) clear.onclick = () => this.setDate(null);
    }
    this.renderCurrentPage();
  },

  onSelectedDate(value) {
    const selected = window.swiftMonitorStore.selectedDate;
    if (!selected) return true;
    if (!value) return false;
    const d = new Date(value);
    const local = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    return local === selected;
  },

  formatDate(isoDate) {
    const [y, m, d] = isoDate.split('-').map(Number);
    return new Date(y, m - 1, d).toLocaleDateString([], { day: 'numeric', month: 'short', year: 'numeric' });
  },

  /** "ACTION_REQUIRED" -> "ACTION REQUIRED" */
  label(value) {
    return String(value ?? '—').replace(/_/g, ' ');
  },

  badge(value) {
    const known = /^[A-Z_]+$/.test(value || '') ? value : '';
    return `<span class="st ${known}">${this.esc(this.label(value))}</span>`;
  },

  prio(priority) {
    const p = priority || 'NORMAL';
    return `<span class="prio prio-${this.esc(p)}">${p.charAt(0)}${p.slice(1).toLowerCase()}</span>`;
  },

  /** One next step per row: Start a new item, Resolve one in progress (both on the detail page). */
  rowActions(row) {
    const ref = this.esc(row.reference);
    if (['PRIORITY', 'ACTION_REQUIRED'].includes(row.status)) {
      return `<div class="actions-cell"><button class="btn ghost sm" data-action="start" data-reference="${ref}">Start</button></div>`;
    }
    if (row.status === 'IN_PROGRESS') {
      return `<div class="actions-cell"><button class="btn sm" data-action="resolve" data-reference="${ref}">Resolve</button></div>`;
    }
    return '';
  },

  /** "ABA_REQUEST" -> "ABA request", "CANCELLATION" -> "Cancellation" */
  categoryLabel(category) {
    if (!category) return '—';
    const words = category.split('_').map((w) => (w === 'ABA' || w === 'CST' ? w : w.toLowerCase()));
    const text = words.join(' ');
    return text.charAt(0).toUpperCase() + text.slice(1);
  },

  bindRowActions(container) {
    container.querySelectorAll('[data-action="start"]').forEach((button) => {
      button.addEventListener('click', () => this.updateStatus(button.dataset.reference, 'IN_PROGRESS'));
    });
    container.querySelectorAll('[data-action="resolve"]').forEach((button) => {
      button.addEventListener('click', () => this.updateStatus(button.dataset.reference, 'RESOLVED'));
    });
  },

  async loadMetrics() {
    try {
      const metrics = await window.swiftMonitorApi.getMetrics();
      window.swiftMonitorStore.metrics = metrics;
      if (metrics.last_processed_at) {
        window.swiftMonitorStore.lastProcessedAt = metrics.last_processed_at;
      }
      return true;
    } catch (error) {
      console.warn('Metrics unavailable:', error);
      return false;
    }
  },

  async loadQueue() {
    try {
      const rows = await window.swiftMonitorApi.listSwifts({ limit: 1000 });
      const normalized = Array.isArray(rows) ? rows : [];
      const previous = window.swiftMonitorStore.rows;
      if (this.queueLoaded) {
        // Toast each item that newly became PRIORITY (new amendment, or a reopened reference).
        normalized
          .filter((row) => row.status === 'PRIORITY' && previous.get(row.reference)?.status !== 'PRIORITY')
          .forEach((row) => window.swiftMonitorAlerts.notifyPriority(row));
      }
      this.queueLoaded = true;
      window.swiftMonitorStore.setRows(normalized);
      window.swiftMonitorAlerts.updateTitle(normalized.filter((row) => row.status === 'PRIORITY').length);
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
    this.lastConnectionCheck = Date.now();
    try {
      const user = await window.swiftMonitorApi.getConnectionStatus();
      const identity = user.userPrincipalName || user.displayName || 'Connected';
      this.setPill('success', `Connected as ${identity}`);
      window.swiftMonitorStore.connection = { connected: true, label: identity, details: user };
    } catch (error) {
      this.setPill('danger', 'Mailbox not connected');
      window.swiftMonitorStore.connection = { connected: false, label: 'Not connected', details: null };
    }

    this.renderHeaderMeta();
  },

  renderHeaderMeta() {
    const activity = document.getElementById('last-activity');
    const metrics = window.swiftMonitorStore.metrics || {};
    if (activity) {
      if (metrics.last_processed_at) {
        activity.textContent = `Last activity ${this.relativeTime(metrics.last_processed_at)} ago`;
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
      const today = metrics.by_status_today || {};
      const priority = metrics.open_priority || 0;
      const failures = metrics.failed_open || 0;
      const tiles = [
        ['SWIFTs today', metrics.swift_today || 0, ''],
        ['Needs action', metrics.open_action_required || 0, ''],
        ['Priority', priority, priority ? 'hot' : ''],
        ['Auto-closed', today.AUTO_CLOSED || 0, ''],
        ['Routed to CST', today.ROUTED_CST || 0, ''],
        ['Auto-replied', today.RESPONDED || 0, ''],
        ['Failures', failures, failures ? 'warn' : ''],
      ];
      container.innerHTML = tiles.map(([label, value, tone]) => `
        <div class="metric-card ${tone}">
          <div class="metric-label">${label}</div>
          <div class="metric-value">${value}</div>
        </div>
      `).join('');
    }

    const alertStrip = document.getElementById('priority-alert-strip');
    if (alertStrip) {
      const openPriorityRows = Array.from(window.swiftMonitorStore.rows.values())
        .filter((row) => row.status === 'PRIORITY' && this.onSelectedDate(row.received_at || row.created_at));
      alertStrip.classList.toggle('show', openPriorityRows.length > 0);
      alertStrip.innerHTML = openPriorityRows.length ? `
        <span class="pulse" aria-hidden="true"></span>
        <strong><span class="count">${openPriorityRows.length}</span>priority ${openPriorityRows.length === 1 ? 'alert' : 'alerts'}</strong>
        ${openPriorityRows.map((row) => `
          <button class="chip" type="button" data-reference="${this.esc(row.reference)}" title="${this.esc(row.business_purpose || '')}">${this.esc(row.reference)} · ${this.esc(this.shortType(row.message_type))}</button>
        `).join('')}` : '';
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
    const rows = window.swiftMonitorStore.getOpenRows().filter((row) => this.onSelectedDate(row.received_at || row.created_at));
    const tableBody = document.getElementById('overview-queue-body');
    if (!tableBody) return;

    if (!rows.length) {
      tableBody.innerHTML = '<tr><td colspan="8" class="empty-state">No open items.</td></tr>';
      return;
    }

    tableBody.innerHTML = rows.slice(0, 8).map((row) => {
      const amount = window.swiftMonitorStore.formatCurrency(row.amount, row.currency);
      return `
        <tr>
          <td class="nowrap">${this.prio(row.priority)}</td>
          <td class="ref-cell" title="${this.esc(row.reference)}"><a href="/swift/${encodeURIComponent(row.reference)}">${this.esc(row.reference)}</a></td>
          <td title="${this.esc(row.message_type || '')}">${this.esc(this.shortType(row.message_type))}</td>
          <td>${this.esc(this.categoryLabel(row.category))}</td>
          <td class="nowrap">${this.esc(amount)}</td>
          <td>${this.relativeTime(row.received_at || row.created_at)}</td>
          <td>${this.badge(row.status)}</td>
          <td>${this.rowActions(row)}</td>
        </tr>
      `;
    }).join('');

    this.bindRowActions(tableBody);
  },

  renderActivityFeed() {
    const feed = document.getElementById('activity-feed');
    if (!feed) return;
    const rows = window.swiftMonitorStore.activity
      .filter((item) => (item.is_swift === 1 || item.is_swift === true) && this.onSelectedDate(item.processed_at)).slice(0, 10);
    if (!rows.length) {
      feed.innerHTML = '<li class="empty-state">No SWIFT activity yet.</li>';
      return;
    }
    feed.innerHTML = rows.map((item) => `
      <li class="activity-item ${item.outcome === 'FAILED' ? 'failed' : ''}">
        <span class="time">${this.formatTime(item.processed_at)}</span>
        ${this.badge(item.outcome === 'FAILED' ? 'FAILED' : (item.status || item.outcome))}
        <span class="ref" title="${this.esc(item.reference || '')}">${this.esc(item.reference || '—')}</span>
        <span class="subject" title="${this.esc(item.subject || '')}">${this.esc(item.subject || '')}</span>
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
      return byStatus && byCategory && byText && this.onSelectedDate(row.received_at || row.created_at);
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
        <td class="nowrap">${this.prio(row.priority)}</td>
        <td class="ref-cell" title="${this.esc(row.reference)}"><a href="/swift/${encodeURIComponent(row.reference)}">${this.esc(row.reference)}</a></td>
        <td title="${this.esc(row.message_type || '')}">${this.esc(this.shortType(row.message_type))}</td>
        <td>${this.esc(this.categoryLabel(row.category))}</td>
        <td>${this.esc(row.sender_bic || '—')}</td>
        <td>${this.esc(window.swiftMonitorStore.formatCurrency(row.amount, row.currency))}</td>
        <td class="clip" title="${this.esc(row.business_purpose || '')}">${this.esc(row.business_purpose || '—')}</td>
        <td>${this.relativeTime(row.received_at || row.created_at)}</td>
        <td>${this.badge(row.status)}</td>
        <td>${this.rowActions(row)}</td>
      </tr>
    `).join('');

    this.bindRowActions(tableBody);
  },

  renderActivityPage() {
    const tableBody = document.getElementById('activity-table-body');
    if (!tableBody) return;

    const outcomeValue = document.getElementById('activity-outcome-filter')?.value || '';
    const swiftOnly = document.getElementById('activity-swift-only')?.checked !== false;

    let rows = window.swiftMonitorStore.activity.filter((item) => {
      const byOutcome = !outcomeValue || item.outcome === outcomeValue;
      const bySwift = !swiftOnly || item.is_swift === 1 || item.is_swift === true;
      return byOutcome && bySwift && this.onSelectedDate(item.processed_at);
    });

    if (!rows.length) {
      tableBody.innerHTML = '<tr><td colspan="8" class="empty-state">No matching activity rows.</td></tr>';
      return;
    }

    tableBody.innerHTML = rows.map((item) => `
      <tr>
        <td>${this.formatTime(item.processed_at)}</td>
        <td>${this.esc(item.folder || '—')}</td>
        <td class="ref-cell" title="${this.esc(item.reference || '')}">${item.reference && window.swiftMonitorStore.rows.has(item.reference)
          ? `<a href="/swift/${encodeURIComponent(item.reference)}">${this.esc(item.reference)}</a>` : this.esc(item.reference || '—')}</td>
        <td>${this.esc(this.categoryLabel(item.category))}</td>
        <td>${this.esc(this.label(item.action))}</td>
        <td>${item.status ? this.badge(item.status) : '—'}</td>
        <td><span title="${this.esc(item.error || '')}">${this.badge(item.outcome)}</span></td>
        <td class="clip" title="${this.esc(item.subject || '')}">${this.esc(item.subject || '')}</td>
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
        <span class="pill ${connection.connected ? 'success' : 'danger'}"><i class="dot"></i><span>${this.esc(statusText)}</span></span>
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
        ${this.badge(item.outcome)}
        <span class="clip" style="max-width:none">${item.reference ? `<span class="mono">${this.esc(item.reference)}</span>` : this.esc(item.subject || '—')}${item.action ? ` · ${this.esc(this.label(item.action))}` : ''}</span>
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
      if (meta) {
        meta.className = 'detail-meta';
        meta.innerHTML = `<span class="tag">${this.esc(row.message_type || 'Unknown')}</span>
          <span class="tag">${this.esc(this.categoryLabel(row.category))}</span>${this.badge(row.status)}`;
      }

      // onclick (not addEventListener): this page re-renders on every poll, and handlers must not pile up.
      const startBtn = document.getElementById('detail-start-btn');
      const resolveBtn = document.getElementById('detail-resolve-btn');
      if (startBtn) {
        startBtn.onclick = () => this.updateStatus(row.reference, 'IN_PROGRESS');
        startBtn.disabled = !['PRIORITY', 'ACTION_REQUIRED'].includes(row.status);
      }
      if (resolveBtn) {
        resolveBtn.onclick = () => this.updateStatus(row.reference, 'RESOLVED');
        resolveBtn.disabled = !['PRIORITY', 'ACTION_REQUIRED', 'IN_PROGRESS'].includes(row.status);
      }

      detailWrap.innerHTML = `
        <div class="detail-card">
          <h3>Key details</h3>
          <dl>
            <div><dt>Related reference</dt><dd>${this.esc(row.related_reference || '—')}</dd></div>
            <div><dt>Sender BIC</dt><dd>${this.esc(row.sender_bic || '—')}</dd></div>
            <div><dt>Receiver BIC</dt><dd>${this.esc(row.receiver_bic || '—')}</dd></div>
            <div><dt>Amount</dt><dd>${this.esc(window.swiftMonitorStore.formatCurrency(row.amount, row.currency))}</dd></div>
            <div><dt>Received</dt><dd>${row.received_at ? new Date(row.received_at).toLocaleString() : '—'}</dd></div>
          </dl>
        </div>
        <div class="detail-card">
          <h3>Business purpose</h3>
          <pre>${this.escapeHtml(row.business_purpose || row.narrative || 'No business purpose available.')}</pre>
        </div>
        <div class="detail-card">
          <h3>Why this category</h3>
          <p>${this.escapeHtml(row.reason || 'No reason supplied.')}</p>
          ${(row.matched_terms || []).length
            ? `<div class="terms">${row.matched_terms.map((term) => `<span class="tag">${this.escapeHtml(term)}</span>`).join('')}</div>`
            : '<p class="muted">No keywords matched.</p>'}
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

  /** "camt.056.001.08" -> "camt.056"; MT types unchanged. */
  shortType(type) {
    if (!type) return '—';
    return /^[a-z]{4}\.\d{3}\./.test(type) ? type.split('.').slice(0, 2).join('.') : type;
  },

  esc(value) {
    return this.escapeHtml(value);
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
