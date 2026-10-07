window.swiftMonitorAlerts = {
  baseTitle: document.title.replace(/^\(\d+\)\s*/, ''),

  showToast(message, tone = 'info', durationMs = 2600) {
    const toast = this._toast(tone);
    if (!toast) return;
    toast.textContent = message;
    this._dismissLater(toast, durationMs);
  },

  /** Amendment alert with the key details the analyst needs; built with textContent (never HTML). */
  notifyPriority(row) {
    const toast = this._toast('warning priority-toast');
    if (!toast) return;
    const title = document.createElement('strong');
    title.textContent = `${row.category === 'AMENDMENT' ? 'Amendment request' : 'Priority item'}: ${row.reference}`;
    const details = document.createElement('div');
    const amount = window.swiftMonitorStore.formatCurrency(row.amount, row.currency);
    details.textContent = [row.message_type, row.sender_bic && `from ${row.sender_bic}`, amount !== '—' && amount,
      row.related_reference && `re ${row.related_reference}`].filter(Boolean).join(' · ');
    const purpose = document.createElement('div');
    purpose.className = 'toast-purpose';
    purpose.textContent = (row.business_purpose || '').slice(0, 120);
    const open = document.createElement('a');
    open.href = `/swift/${encodeURIComponent(row.reference)}`;
    open.textContent = 'Open';
    toast.append(title, details, purpose, open);
    this._dismissLater(toast, 10000);
  },

  /** Show the number of open priority items in the tab title, e.g. "(2) SWIFT Monitor". */
  updateTitle(openPriority) {
    document.title = openPriority > 0 ? `(${openPriority}) ${this.baseTitle}` : this.baseTitle;
  },

  _toast(tone) {
    const container = document.getElementById('toast-container');
    if (!container) return null;
    const toast = document.createElement('div');
    toast.className = `toast ${tone}`;
    container.appendChild(toast);
    return toast;
  },

  _dismissLater(toast, durationMs) {
    setTimeout(() => {
      toast.classList.add('fade-out');
      setTimeout(() => toast.remove(), 350);
    }, durationMs);
  },
};
