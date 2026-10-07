window.swiftMonitorPoller = {
  intervalId: null,
  backoffMs: 3000,
  timerStarted: false,

  schedule() {
    if (this.intervalId) return;
    this.intervalId = setInterval(() => {
      if (document.visibilityState === 'hidden') return;
      if (window.swiftMonitorApp && typeof window.swiftMonitorApp.refreshAll === 'function') {
        window.swiftMonitorApp.refreshAll();
      }
    }, 5000);
    this.timerStarted = true;
  },

  stop() {
    if (this.intervalId) {
      clearInterval(this.intervalId);
      this.intervalId = null;
    }
  },
};
