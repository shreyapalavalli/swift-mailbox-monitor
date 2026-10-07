window.swiftMonitorAlerts = {
  showToast(message, tone = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast ${tone}`;
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(() => {
      toast.classList.add('fade-out');
      setTimeout(() => toast.remove(), 350);
    }, 2600);
  },

  async notifyPriority(row) {
    const message = `Amendment request: ${row.reference}`;
    this.showToast(message, 'warning');
    if (document.title.includes('SWIFT')) {
      const current = document.title.replace(/^\(\d+\)\s*/, '');
      document.title = `(1) ${current}`;
    }
  },
};
