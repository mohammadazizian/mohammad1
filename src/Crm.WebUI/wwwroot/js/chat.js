/*
 * Contextual chat widget ("chatter").
 * The markup comes from _ChatPanelPartial; this script adds:
 *  - a SignalR subscription to the open entity's group (live messages + typing hints)
 *  - posting messages (with attachments and thread replies) without a page reload
 *  - auto-complete for @user mentions and #object links
 */
(function () {
  'use strict';

  const app = window.crm;
  let connection = null;
  let current = null; // { root, type, id }

  function ensureConnection() {
    if (connection) return connection;

    connection = new signalR.HubConnectionBuilder()
      .withUrl('/hubs/chat')
      .withAutomaticReconnect()
      .configureLogging(signalR.LogLevel.Warning)
      .build();

    connection.on('messagePosted', (e) => {
      if (isCurrent(e)) showMessage(e.messageId, e.parentMessageId);
    });

    connection.on('typing', (e) => {
      if (!isCurrent(e)) return;
      const indicator = current.root.querySelector('[data-chat-typing]');
      indicator.textContent = app.format(app.texts.typing, e.name);
      clearTimeout(indicator._timer);
      indicator._timer = setTimeout(() => (indicator.textContent = ''), 2500);
    });

    // After a reconnect the server-side group membership is gone: join again.
    connection.onreconnected(() => current && connection.invoke('JoinEntity', current.type, current.id));
    return connection;
  }

  const isCurrent = (e) => current && e.entityType === current.type && e.entityId === current.id;

  async function join(root) {
    current = { root, type: root.dataset.entityType, id: root.dataset.entityId };
    const hub = ensureConnection();
    try {
      if (hub.state === signalR.HubConnectionState.Disconnected) await hub.start();
      await hub.invoke('JoinEntity', current.type, current.id);
    } catch (err) {
      console.warn('Chat hub unavailable - messages will still be saved', err);
    }
  }

  function leave() {
    if (current && connection?.state === signalR.HubConnectionState.Connected) {
      connection.invoke('LeaveEntity', current.type, current.id).catch(() => {});
    }
    current = null;
  }

  // ---- Rendering --------------------------------------------------------------------------
  async function showMessage(id, parentId) {
    if (!current || document.getElementById('msg-' + id)) return;

    const response = await fetch(`/Collab/Chat?handler=Message&id=${id}`, { headers: { 'X-Requested-With': 'XMLHttpRequest' } });
    if (!response.ok || !current || document.getElementById('msg-' + id)) return;

    const template = document.createElement('template');
    template.innerHTML = (await response.text()).trim();

    const list = current.root.querySelector('[data-chat-messages]');
    const target = (parentId && document.getElementById('replies-' + parentId)) || list;
    current.root.querySelector('[data-chat-empty]')?.remove();
    target.appendChild(template.content);
    list.scrollTop = list.scrollHeight;

    document.querySelectorAll(`[data-chat-count="${current.root.dataset.entity}"]`).forEach((badge) => {
      badge.textContent = current.root.querySelectorAll('.chat-message').length.toLocaleString(document.documentElement.lang);
    });
  }

  // ---- Composer ---------------------------------------------------------------------------
  function initComposer(root) {
    const form = root.querySelector('[data-chat-form]');
    if (!form) return;

    const input = form.querySelector('[data-chat-input]');
    const files = form.querySelector('[data-chat-files]');
    const fileNames = form.querySelector('[data-chat-file-names]');
    const parent = form.querySelector('[data-chat-parent]');
    const reply = form.querySelector('[data-chat-reply]');
    const suggestions = form.querySelector('[data-chat-suggestions]');
    let lastTyping = 0;

    const setReply = (id, author) => {
      parent.value = id || '';
      reply.classList.toggle('show', !!id);
      reply.querySelector('[data-chat-reply-label]').textContent = id ? app.format(app.texts.replyingTo, author) : '';
      if (id) input.focus();
    };

    root.addEventListener('click', (e) => {
      const button = e.target.closest('[data-chat-reply-to]');
      if (button) setReply(button.dataset.chatReplyTo, button.dataset.author);
      if (e.target.closest('[data-chat-reply-cancel]')) setReply(null);
    });

    files.addEventListener('change', () => {
      fileNames.textContent = Array.from(files.files).map((f) => f.name).join(', ');
    });

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (!input.value.trim() && files.files.length === 0) return;

      const submit = form.querySelector('[type="submit"]');
      submit.disabled = true;
      try {
        const response = await fetch('/Collab/Chat', {
          method: 'POST',
          body: new FormData(form),
          headers: { RequestVerificationToken: app.csrfToken(), 'X-Requested-With': 'XMLHttpRequest' },
        });

        if (!response.ok) {
          const problem = await response.json().catch(() => ({}));
          app.toast({ message: problem.detail || problem.title || app.texts.error, type: 'danger' });
          return;
        }

        const posted = await response.json();
        input.value = '';
        files.value = '';
        fileNames.textContent = '';
        setReply(null);
        // Normally SignalR delivers the message; this covers a dropped connection.
        await showMessage(posted.id, posted.parentId);
      } catch {
        app.toast({ message: app.texts.error, type: 'danger' });
      } finally {
        submit.disabled = false;
        input.focus();
      }
    });

    // Enter sends, Shift+Enter inserts a new line.
    input.addEventListener('keydown', (e) => {
      if (suggestions.classList.contains('show')) {
        if (handleSuggestionKeys(e)) return;
      }
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
        e.preventDefault();
        form.requestSubmit();
      }
    });

    // ---- @mention / #object auto-complete -------------------------------------------------
    let items = [];
    let active = 0;
    let token = null; // { kind: '@' | '#', start, end }
    let requestId = 0;

    input.addEventListener('input', async () => {
      const now = Date.now();
      if (now - lastTyping > 2000 && connection?.state === signalR.HubConnectionState.Connected && current) {
        lastTyping = now;
        connection.invoke('Typing', current.type, current.id).catch(() => {});
      }

      const caret = input.selectionStart;
      const match = /(^|\s)([@#])([^\s@#\[\]|]{0,40})$/u.exec(input.value.slice(0, caret));
      if (!match) return hideSuggestions();

      token = { kind: match[2], start: caret - match[3].length - 1, end: caret };
      const handler = token.kind === '@' ? 'Mentions' : 'Objects';
      const myRequest = ++requestId;
      const response = await fetch(`/Collab/Chat?handler=${handler}&q=${encodeURIComponent(match[3])}`, { headers: { 'X-Requested-With': 'XMLHttpRequest' } });
      if (!response.ok || myRequest !== requestId) return;

      items = await response.json();
      active = 0;
      renderSuggestions();
    });

    input.addEventListener('blur', () => setTimeout(hideSuggestions, 150));

    function renderSuggestions() {
      suggestions.replaceChildren();
      if (items.length === 0) return hideSuggestions();

      items.forEach((item, index) => {
        const row = document.createElement('div');
        row.className = 'chat-suggestion' + (index === active ? ' active' : '');
        row.setAttribute('role', 'option');

        const icon = document.createElement('i');
        icon.className = 'bi ' + (token.kind === '@' ? 'bi-person' : item.icon);
        const label = document.createElement('span');
        label.textContent = item.label;
        const hint = document.createElement('small');
        hint.textContent = token.kind === '@' ? '@' + item.value : item.typeLabel;

        row.append(icon, label, hint);
        row.addEventListener('mousedown', (e) => { e.preventDefault(); pick(index); });
        suggestions.appendChild(row);
      });
      suggestions.classList.add('show');
    }

    function hideSuggestions() {
      suggestions.classList.remove('show');
      items = [];
    }

    function handleSuggestionKeys(e) {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        active = (active + (e.key === 'ArrowDown' ? 1 : items.length - 1)) % items.length;
        renderSuggestions();
        return true;
      }
      if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault();
        pick(active);
        return true;
      }
      if (e.key === 'Escape') {
        e.stopPropagation();
        hideSuggestions();
        return true;
      }
      return false;
    }

    function pick(index) {
      const item = items[index];
      if (!item || !token) return;

      // Mentions are stored as @username, object links as #[Type:Guid|Label].
      const text = token.kind === '@'
        ? `@${item.value} `
        : `#[${item.type}:${item.id}|${item.label.replace(/[\[\]|]/g, ' ').trim()}] `;

      input.value = input.value.slice(0, token.start) + text + input.value.slice(token.end);
      const caret = token.start + text.length;
      input.setSelectionRange(caret, caret);
      hideSuggestions();
      input.focus();
    }
  }

  // ---- Lifecycle: the panel is swapped into the drawer by htmx -------------------------------
  document.body.addEventListener('htmx:afterSwap', (e) => {
    const root = e.target.querySelector?.('[data-chat]');
    if (!root) return;

    leave();
    join(root);
    initComposer(root);
    const list = root.querySelector('[data-chat-messages]');
    list.scrollTop = list.scrollHeight;
  });

  document.addEventListener('crm:drawer-closed', leave);
})();
