window.swiftMonitorPoller = {
  INTERVAL_MS: 5000,
  MAX_BACKOFF_MS: 30000,
  delayMs: 5000,
  timerId: null,
  running: false,

  /** Poll now, then keep polling: every 5 s while the backend answers, backing off to 30 s while it doesn't. */
  schedule() {
    if (this.running) return;
    this.running = true;
    this.pollNow();
  },

  async pollNow() {
    clearTimeout(this.timerId);
    if (document.visibilityState !== 'hidden') {
      const ok = await window.swiftMonitorApp.refreshAll();
      this.delayMs = ok ? this.INTERVAL_MS : Math.min(this.delayMs * 2, this.MAX_BACKOFF_MS);
    }
    if (this.running) this.timerId = setTimeout(() => this.pollNow(), this.delayMs);
  },

  stop() {
    this.running = false;
    clearTimeout(this.timerId);
  },
};
