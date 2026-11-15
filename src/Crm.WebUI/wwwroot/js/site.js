/*
 * Application shell behaviour (unobtrusive: everything is wired through data-* attributes).
 *  - htmx integration: anti-forgery header, error toasts, server-triggered toasts
 *  - slide-over drawer for secondary actions (chat, tasks)
 *  - real-time notifications over SignalR
 *  - Chart.js bootstrapping for <canvas data-chart>
 */
(function () {
  'use strict';

  const texts = JSON.parse(document.getElementById('clientTexts')?.textContent || '{}');
  const csrfToken = () => document.querySelector('meta[name="csrf-token"]')?.content || '';

  const app = (window.crm = {
    texts,
    csrfToken,
    format: (template, ...args) => (template || '').replace(/\{(\d+)\}/g, (_, i) => args[i] ?? ''),
    entityUrl: (type, id) => `/Go/${encodeURIComponent(type)}/${encodeURIComponent(id)}`,
  });

  // ---- Toasts ---------------------------------------------------------------------------
  const toastIcons = { success: 'bi-check-circle-fill text-success', danger: 'bi-exclamation-octagon-fill text-danger', info: 'bi-bell-fill text-primary', warning: 'bi-exclamation-triangle-fill text-warning' };

  app.toast = function ({ message, title, type = 'success', url }) {
    const container = document.getElementById('toastContainer');
    if (!container || !message) return;

    const el = document.createElement('div');
    el.className = 'toast';
    el.setAttribute('role', 'status');
    el.innerHTML = `
      <div class="toast-body d-flex gap-2 align-items-start">
        <i class="bi toast-icon ${toastIcons[type] || toastIcons.info}"></i>
        <div class="flex-grow-1" style="min-inline-size:0">
          <div class="fw-semibold" data-title></div>
          <div dir="auto" data-message></div>
          <a class="small fw-medium d-none" data-link></a>
        </div>
        <button type="button" class="btn-close" data-bs-dismiss="toast"></button>
      </div>`;
    // textContent (not innerHTML) so user-provided text can never inject markup.
    el.querySelector('[data-title]').textContent = title || '';
    el.querySelector('[data-message]').textContent = message;
    if (!title) el.querySelector('[data-title]').remove();
    if (url) {
      const link = el.querySelector('[data-link]');
      link.href = url;
      link.textContent = texts.open;
      link.classList.remove('d-none');
    }
    container.appendChild(el);
    el.addEventListener('hidden.bs.toast', () => el.remove());
    new bootstrap.Toast(el, { delay: type === 'danger' ? 7000 : 4500 }).show();
  };

  // Toast handed over by the server across a redirect (TempData).
  document.addEventListener('DOMContentLoaded', () => {
    const pending = document.body.dataset.toast;
    if (pending) {
      try { app.toast(JSON.parse(pending)); } catch { /* ignore malformed payloads */ }
    }
  });

  // ---- htmx -----------------------------------------------------------------------------
  document.body.addEventListener('htmx:configRequest', (e) => {
    e.detail.headers['RequestVerificationToken'] = csrfToken();
  });

  // Toast requested by the server through the HX-Trigger response header.
  document.body.addEventListener('toast', (e) => {
    const detail = e.detail || {};
    app.toast({ message: decodeURIComponent(detail.message || ''), type: detail.type });
  });

  // Failed htmx requests answer with RFC 7807 problem details (see GlobalExceptionHandler).
  document.body.addEventListener('htmx:responseError', (e) => {
    let message = texts.error;
    try {
      const problem = JSON.parse(e.detail.xhr.responseText);
      message = problem.detail || problem.title || message;
    } catch { /* not JSON */ }
    app.toast({ message, type: 'danger' });
  });

  document.body.addEventListener('htmx:sendError', () => app.toast({ message: texts.error, type: 'danger' }));

  // Plain (non-htmx) forms and links can ask for a confirmation with data-confirm.
  document.addEventListener('submit', (e) => {
    const message = e.target.dataset?.confirm ?? e.submitter?.dataset?.confirm;
    if (message !== undefined && !window.confirm(message || texts.confirm)) e.preventDefault();
  });

  // ---- Drawer ---------------------------------------------------------------------------
  const drawerEl = document.getElementById('appDrawer');
  const drawerBody = document.getElementById('appDrawerBody');

  document.addEventListener('click', (e) => {
    const trigger = e.target.closest('[data-drawer-url]');
    if (!trigger || !drawerEl) return;
    e.preventDefault();
    document.getElementById('appDrawerTitle').textContent = trigger.dataset.drawerTitle || '';
    drawerBody.innerHTML = '<div class="p-5 text-center text-muted"><span class="spinner-border spinner-border-sm"></span></div>';
    bootstrap.Offcanvas.getOrCreateInstance(drawerEl).show();
    htmx.ajax('GET', trigger.dataset.drawerUrl, { target: '#appDrawerBody', swap: 'innerHTML' });
  });

  drawerEl?.addEventListener('hidden.bs.offcanvas', () => {
    document.dispatchEvent(new CustomEvent('crm:drawer-closed'));
    drawerBody.innerHTML = '';
  });

  // Keep the counters on the collaboration buttons in sync with the widgets.
  document.body.addEventListener('htmx:afterSwap', (e) => {
    const widget = e.target.matches?.('[data-task-widget]') ? e.target : e.target.querySelector?.('[data-task-widget]');
    if (widget) {
      document.querySelectorAll(`[data-task-count="${widget.dataset.entity}"]`).forEach((badge) => {
        badge.textContent = Number(widget.dataset.openCount).toLocaleString(document.documentElement.lang);
        badge.classList.toggle('pill-warning', Number(widget.dataset.openCount) > 0);
      });
    }

    const unread = e.target.querySelector?.('[data-unread]');
    if (unread) setUnread(Number(unread.dataset.unread));

    initCharts(e.target);
  });

  // ---- Notifications (SignalR) ----------------------------------------------------------
  const badge = document.getElementById('notificationBadge');

  function setUnread(count) {
    if (!badge) return;
    badge.dataset.count = count;
    badge.textContent = count > 99 ? '99+' : count.toLocaleString(document.documentElement.lang);
    badge.classList.toggle('d-none', count <= 0);
  }

  if (badge && window.signalR) {
    const connection = new signalR.HubConnectionBuilder()
      .withUrl('/hubs/notifications')
      .withAutomaticReconnect()
      .configureLogging(signalR.LogLevel.Warning)
      .build();

    connection.on('notification', (n) => {
      setUnread(Number(badge.dataset.count || 0) + 1);
      app.toast({
        title: texts['notification.' + n.type] || n.type,
        message: n.message,
        type: n.type === 'LowStock' ? 'warning' : 'info',
        url: n.entityType && n.entityId ? app.entityUrl(n.entityType, n.entityId) : '/Tasks',
      });
      document.dispatchEvent(new CustomEvent('crm:notification', { detail: n }));
    });

    connection.start().catch((err) => console.warn('Notification hub unavailable', err));
    app.notifications = connection;
  }

  // ---- Charts ---------------------------------------------------------------------------
  const palette = ['#4f46e5', '#0f9d6b', '#e58a00', '#d13a4a', '#0e8fb3', '#8b5cf6', '#64748b', '#db2777', '#65a30d', '#b45309'];

  function initCharts(root) {
    if (!window.Chart) return;
    (root.querySelectorAll ? root.querySelectorAll('canvas[data-chart]') : []).forEach((canvas) => {
      if (canvas.dataset.ready) return;
      canvas.dataset.ready = '1';

      const config = JSON.parse(canvas.dataset.chart);
      const circular = config.type === 'pie' || config.type === 'doughnut';
      const rtl = document.documentElement.dir === 'rtl';
      Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
      Chart.defaults.color = '#6b7385';

      new Chart(canvas, {
        type: config.type,
        data: {
          labels: config.labels,
          datasets: [{
            label: config.label,
            data: config.values,
            backgroundColor: circular ? palette : (config.type === 'line' ? 'rgba(79,70,229,.12)' : '#4f46e5'),
            borderColor: circular ? '#fff' : '#4f46e5',
            borderWidth: circular ? 2 : (config.type === 'line' ? 2 : 0),
            borderRadius: config.type === 'bar' ? 6 : 0,
            maxBarThickness: 44,
            fill: config.type === 'line',
            tension: 0.3,
          }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          locale: document.documentElement.lang,
          plugins: {
            legend: { display: circular, position: 'bottom', rtl, labels: { usePointStyle: true, boxWidth: 8 } },
            tooltip: { rtl, textDirection: rtl ? 'rtl' : 'ltr' },
          },
          scales: circular ? {} : {
            x: { reverse: rtl, grid: { display: false } },
            y: { position: rtl ? 'right' : 'left', beginAtZero: true, grid: { color: '#eef0f3' }, ticks: { precision: config.values.every(Number.isInteger) ? 0 : undefined } },
          },
        },
      });
    });
  }

  app.initCharts = initCharts;
  document.addEventListener('DOMContentLoaded', () => initCharts(document));
})();
