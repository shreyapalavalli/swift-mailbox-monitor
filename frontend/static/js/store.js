window.swiftMonitorStore = {
  rows: new Map(),
  metrics: {},
  activity: [],
  connection: { connected: false, label: 'Unknown', details: null },
  cursor: null,
  lastProcessedAt: null,
  page: 'overview',

  setPage(page) {
    this.page = page;
  },

  setRows(rows) {
    this.rows = new Map(rows.map((item) => [item.reference, item]));
  },

  setCursor(list) {
    if (!list.length) return;
    const values = list.map((item) => item.updated_at || item.received_at || '').filter(Boolean);
    this.cursor = values.reduce((max, value) => (value > max ? value : max), this.cursor || values[0]);
  },

  getOpenRows() {
    const rows = Array.from(this.rows.values()).filter((row) =>
      ['PRIORITY', 'ACTION_REQUIRED', 'IN_PROGRESS'].includes(row.status)
    );
    return rows.sort((a, b) => {
      const priorityOrder = { HIGH: 0, NORMAL: 1, LOW: 2 };
      const priorityDelta = (priorityOrder[a.priority] ?? 99) - (priorityOrder[b.priority] ?? 99);
      if (priorityDelta !== 0) return priorityDelta;
      return (a.received_at || '').localeCompare(b.received_at || '');
    });
  },

  formatCurrency(value, currency) {
    if (!value || !currency) return '—';
    const amount = Number(value);
    if (!Number.isFinite(amount)) return value;
    try {
      return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency,
        maximumFractionDigits: 2,
      }).format(amount);
    } catch (error) {
      return `${value} ${currency}`;
    }
  },
};
