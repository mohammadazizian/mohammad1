/*
 * Dynamic form designer. The DOM is the single source of truth: field cards are cloned from
 * <template> elements and serialized to JSON (hidden input "FieldsJson") when the form is saved.
 */
(function () {
  'use strict';

  const form = document.querySelector('[data-form-builder]');
  if (!form) return;

  const list = form.querySelector('[data-fields]');
  const empty = form.querySelector('[data-fields-empty]');
  const hidden = form.querySelector('[data-fields-json]');
  const fieldTemplate = document.getElementById('fieldTemplate');
  const optionTemplate = document.getElementById('optionTemplate');

  const get = (root, prop) => root.querySelector(`[data-prop="${prop}"]`);
  const numberOrNull = (value) => (value === '' || value === null || Number.isNaN(Number(value)) ? null : Number(value));

  function addOption(card, option = {}) {
    const row = optionTemplate.content.firstElementChild.cloneNode(true);
    row.querySelector('[data-opt="value"]').value = option.value ?? '';
    row.querySelector('[data-opt="labelEn"]').value = option.label?.en ?? '';
    row.querySelector('[data-opt="labelFa"]').value = option.label?.fa ?? '';
    card.querySelector('[data-options]').appendChild(row);
  }

  function addField(field = {}) {
    const card = fieldTemplate.content.firstElementChild.cloneNode(true);
    get(card, 'type').value = field.type ?? 'Text';
    get(card, 'key').value = field.key ?? '';
    get(card, 'labelEn').value = field.label?.en ?? '';
    get(card, 'labelFa').value = field.label?.fa ?? '';
    get(card, 'required').checked = !!field.required;
    get(card, 'min').value = field.min ?? '';
    get(card, 'max').value = field.max ?? '';
    get(card, 'maxLength').value = field.maxLength ?? '';
    get(card, 'pattern').value = field.pattern ?? '';
    if (field.lookupEntityType) get(card, 'lookupEntityType').value = field.lookupEntityType;
    (field.options ?? []).forEach((option) => addOption(card, option));
    list.appendChild(card);
    refresh();
    return card;
  }

  // Shows only the settings that apply to each field's type and renumbers the cards.
  function refresh() {
    const cards = [...list.querySelectorAll('[data-field]')];
    empty.classList.toggle('d-none', cards.length > 0);
    cards.forEach((card, index) => {
      const type = get(card, 'type').value;
      card.querySelector('[data-index]').textContent = (index + 1).toLocaleString(document.documentElement.lang);
      card.querySelector('[data-summary]').textContent = get(card, 'labelEn').value || get(card, 'key').value;
      card.querySelectorAll('[data-for]').forEach((el) => el.classList.toggle('d-none', !el.dataset.for.split(' ').includes(type)));
      if (type === 'Dropdown' && !card.querySelector('[data-option]')) addOption(card);
    });
  }

  function serialize() {
    return [...list.querySelectorAll('[data-field]')].map((card) => {
      const type = get(card, 'type').value;
      return {
        key: get(card, 'key').value.trim(),
        type,
        label: { en: get(card, 'labelEn').value.trim(), fa: get(card, 'labelFa').value.trim() },
        required: get(card, 'required').checked,
        min: type === 'Number' ? numberOrNull(get(card, 'min').value) : null,
        max: type === 'Number' ? numberOrNull(get(card, 'max').value) : null,
        maxLength: type === 'Text' || type === 'TextArea' ? numberOrNull(get(card, 'maxLength').value) : null,
        pattern: type === 'Text' ? get(card, 'pattern').value.trim() || null : null,
        lookupEntityType: type === 'EntityLookup' ? get(card, 'lookupEntityType').value : null,
        options: type !== 'Dropdown' ? [] : [...card.querySelectorAll('[data-option]')]
          .map((row) => ({
            value: row.querySelector('[data-opt="value"]').value.trim(),
            label: { en: row.querySelector('[data-opt="labelEn"]').value.trim(), fa: row.querySelector('[data-opt="labelFa"]').value.trim() },
          }))
          .filter((option) => option.value),
      };
    });
  }

  // Suggest a key from the English label ("Visit date" -> "visitDate") until the user edits it.
  function suggestKey(card) {
    const key = get(card, 'key');
    if (key.dataset.touched) return;
    const words = get(card, 'labelEn').value.replace(/[^A-Za-z0-9 ]/g, ' ').trim().split(/\s+/).filter(Boolean);
    key.value = words.map((w, i) => (i === 0 ? w.toLowerCase() : w[0].toUpperCase() + w.slice(1).toLowerCase())).join('').replace(/^[0-9]+/, '');
  }

  form.addEventListener('click', (e) => {
    const card = e.target.closest('[data-field]');
    if (e.target.closest('[data-add-field]')) {
      addField().querySelector('[data-prop="labelEn"]').focus();
    } else if (e.target.closest('[data-remove]')) {
      card.remove();
    } else if (e.target.closest('[data-move]')) {
      const direction = Number(e.target.closest('[data-move]').dataset.move);
      const sibling = direction < 0 ? card.previousElementSibling : card.nextElementSibling;
      if (sibling) direction < 0 ? sibling.before(card) : sibling.after(card);
    } else if (e.target.closest('[data-add-option]')) {
      addOption(card);
    } else if (e.target.closest('[data-remove-option]')) {
      e.target.closest('[data-option]').remove();
    } else {
      return;
    }
    refresh();
  });

  form.addEventListener('input', (e) => {
    const card = e.target.closest('[data-field]');
    if (!card) return;
    if (e.target.dataset.prop === 'key') e.target.dataset.touched = '1';
    if (e.target.dataset.prop === 'labelEn') suggestKey(card);
    refresh();
  });

  form.addEventListener('submit', () => { hidden.value = JSON.stringify(serialize()); });

  // Initial state: the saved schema (or what the user posted before a validation error).
  let initial = [];
  try { initial = JSON.parse(hidden.value || '[]'); } catch { /* start empty */ }
  initial.forEach((field) => { const card = addField(field); get(card, 'key').dataset.touched = '1'; });
  refresh();
})();
