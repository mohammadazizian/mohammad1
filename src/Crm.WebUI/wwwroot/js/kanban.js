/*
 * Kanban drag & drop for the deal pipeline (native HTML5 drag and drop, event delegation so it
 * keeps working after htmx re-renders the board). Dropping a card posts the move through htmx.
 */
(function () {
  'use strict';

  let dragged = null;

  document.addEventListener('dragstart', (e) => {
    const card = e.target.closest?.('.kanban-card');
    if (!card || card.closest('[data-kanban]')?.dataset.canMove !== 'true') return;
    dragged = card;
    card.classList.add('dragging');
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', card.dataset.dealId);
  });

  document.addEventListener('dragend', () => {
    dragged?.classList.remove('dragging');
    dragged = null;
    document.querySelectorAll('.kanban-cards.drag-over').forEach((el) => el.classList.remove('drag-over'));
  });

  document.addEventListener('dragover', (e) => {
    const column = e.target.closest?.('.kanban-cards');
    if (!column || !dragged) return;
    e.preventDefault();
    document.querySelectorAll('.kanban-cards.drag-over').forEach((el) => el !== column && el.classList.remove('drag-over'));
    column.classList.add('drag-over');
  });

  document.addEventListener('drop', (e) => {
    const column = e.target.closest?.('.kanban-cards');
    if (!column || !dragged) return;
    e.preventDefault();

    const board = column.closest('[data-kanban]');
    const dealId = dragged.dataset.dealId;
    if (dragged.parentElement === column) return;

    column.appendChild(dragged); // optimistic move; the server response re-renders the board
    htmx.ajax('POST', board.dataset.moveUrl, {
      target: '#board',
      swap: 'innerHTML',
      values: { dealId, stageId: column.dataset.stageId },
    }).catch(() => htmx.ajax('GET', '/Deals', { target: '#board', swap: 'innerHTML' }));
  });

  // If the move is rejected (validation / permission), reload the authoritative board.
  document.body.addEventListener('htmx:responseError', (e) => {
    if (e.detail.pathInfo?.requestPath?.startsWith('/Deals')) {
      htmx.ajax('GET', '/Deals', { target: '#board', swap: 'innerHTML' });
    }
  });
})();
