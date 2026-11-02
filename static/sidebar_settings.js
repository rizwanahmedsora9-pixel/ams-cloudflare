/* Sidebar Settings page (Settings -> Sidebar Settings).
 *
 * Data driven sidebar designer: the page renders "all options" on the left and
 * the saved layout (categories + top level) on the right.  Dragging an option
 * into a category, onto the top level, or onto the left panel (remove from the
 * sidebar) updates a local model and POSTs the whole snapshot to
 * /settings/sidebar/save.
 *
 * Configuration is passed by templates/sidebar_settings.html in a
 * <script type="application/json" id="sbConfig"> block:
 *     { links: [...], layout: {...}, saveUrl: "...", resetUrl: "..." }
 *
 * Offline DOM test: node tests/frontend/test_sidebar_settings_dom.js
 */
(function () {
    'use strict';

    function readConfig() {
        const holder = document.getElementById('sbConfig');
        if (!holder) { return {}; }
        try {
            return JSON.parse(holder.textContent || '{}') || {};
        } catch (err) {
            console.error('Sidebar Settings: invalid configuration block.');
            return {};
        }
    }

    let initialised = false;

    function init() {
        // A page script can be started twice (script readyState + a late
        // DOMContentLoaded); never wire the handlers twice.
        if (initialised) { return; }
        initialised = true;

        const CONFIG = readConfig();
        const LINKS = CONFIG.links || [];
        const LINK_BY_KEY = {};
        LINKS.forEach(function (l) { LINK_BY_KEY[l.key] = l; });

        const SAVE_URL = CONFIG.saveUrl;
        const RESET_URL = CONFIG.resetUrl;
        const DEFAULT_ICON = 'bi-folder2';

        if (!window.bootstrap) {
            console.error('Bootstrap is not available — Sidebar Settings cannot open its dialogs.');
        }

        // ------------------------------------------------------------------
        // model
        // ------------------------------------------------------------------
        let layout = normalize(CONFIG.layout);
        let dragState = null;
        let searchTerm = '';
        let editingCategoryKey = null;
        let editingItemKey = null;

        function normalize(raw) {
            const data = raw || {};
            const categories = (data.categories || []).map(function (c) {
                return {
                    key: c.key,
                    name: c.name || 'Category',
                    icon: c.icon || DEFAULT_ICON,
                    is_active: c.is_active !== false
                };
            });
            const known = {};
            categories.forEach(function (c) { known[c.key] = true; });
            const seen = {};
            const items = [];
            (data.items || []).forEach(function (i) {
                if (!i || !LINK_BY_KEY[i.key] || seen[i.key]) { return; }
                seen[i.key] = true;
                items.push({
                    key: i.key,
                    category: (i.category && known[i.category]) ? i.category : null,
                    hidden: !!i.hidden,
                    label: i.label || null,
                    icon: i.icon || null
                });
            });
            LINKS.forEach(function (l) {
                if (seen[l.key]) { return; }
                seen[l.key] = true;
                items.push({
                    key: l.key,
                    category: (l.default_category && known[l.default_category]) ? l.default_category : null,
                    hidden: false,
                    label: null,
                    icon: null
                });
            });
            return { categories: categories, items: items };
        }

        function itemByKey(key) {
            for (let i = 0; i < layout.items.length; i += 1) {
                if (layout.items[i].key === key) { return layout.items[i]; }
            }
            return null;
        }
        function categoryByKey(key) {
            for (let i = 0; i < layout.categories.length; i += 1) {
                if (layout.categories[i].key === key) { return layout.categories[i]; }
            }
            return null;
        }
        function newCategoryKey() {
            let key;
            do {
                key = 'cat_' + Math.random().toString(36).slice(2, 8);
            } while (categoryByKey(key));
            return key;
        }
        function esc(value) {
            return String(value == null ? '' : value)
                .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
        }
        function iconClass(value, fallback) {
            let text = String(value || fallback || DEFAULT_ICON).trim();
            if (text.indexOf('bi bi-') === 0) { text = text.slice(3); }
            if (text.indexOf('bi-') !== 0) { text = 'bi-' + text.replace(/^bi-?/, ''); }
            if (!/^bi-[a-z0-9-]+$/.test(text)) { text = fallback || DEFAULT_ICON; }
            return text;
        }
        function bucketItems(bucket) {
            return layout.items.filter(function (i) {
                if (i.hidden) { return false; }
                if (bucket === '__root') { return !i.category; }
                return i.category === bucket;
            });
        }

        // ------------------------------------------------------------------
        // persistence
        // ------------------------------------------------------------------
        const statusEl = document.getElementById('sbStatus');
        let saveTimer = null;
        let saveSeq = 0;

        function setStatus(text, cls) {
            statusEl.textContent = text;
            statusEl.className = 'badge sb-status ' + (cls || 'bg-dark border border-secondary');
        }

        function scheduleSave() {
            setStatus('Saving…', 'bg-warning text-dark');
            if (saveTimer) { clearTimeout(saveTimer); }
            const seq = ++saveSeq;
            saveTimer = setTimeout(function () { save(seq); }, 250);
        }

        function payload() {
            return {
                categories: layout.categories.map(function (c) {
                    return { key: c.key, name: c.name, icon: c.icon, is_active: c.is_active };
                }),
                items: layout.items.map(function (i) {
                    return {
                        key: i.key,
                        category: i.hidden ? null : i.category,
                        hidden: !!i.hidden,
                        label: i.label,
                        icon: i.icon
                    };
                })
            };
        }

        function save(seq) {
            fetch(SAVE_URL, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload())
            }).then(function (resp) {
                return resp.json().then(function (data) { return { ok: resp.ok, data: data }; });
            }).then(function (res) {
                if (seq !== saveSeq) { return; }
                if (res.ok && res.data && res.data.ok) {
                    setStatus('All changes saved', 'bg-success text-dark');
                } else {
                    setStatus('Not saved', 'bg-danger text-white');
                    window.alert((res.data && res.data.error) || 'The sidebar could not be saved.');
                }
            }).catch(function () {
                if (seq !== saveSeq) { return; }
                setStatus('Not saved', 'bg-danger text-white');
                window.alert('Could not reach the server — the sidebar layout was not saved.');
            });
        }

        // ------------------------------------------------------------------
        // rendering
        // ------------------------------------------------------------------
        function optionRow(item, options) {
            const opts = options || {};
            const link = LINK_BY_KEY[item.key];
            const label = item.label || link.label;
            const icon = iconClass(item.icon, link.icon);
            return '' +
                '<div class="sb-option" draggable="true" data-kind="item" data-key="' + esc(item.key) + '">' +
                    '<i class="bi bi-grip-vertical sb-grip"></i>' +
                    '<i class="bi ' + esc(icon) + ' text-warning"></i>' +
                    '<div class="sb-name">' +
                        '<strong>' + esc(label) + '</strong>' +
                        (opts.showDescription === false ? '' : '<small>' + esc(link.description || '') + '</small>') +
                    '</div>' +
                    (opts.badge || '') +
                    (opts.actions || '') +
                '</div>';
        }

        function itemActions(key) {
            return '' +
                '<button type="button" class="sb-icon-btn" data-act="item-up" data-key="' + esc(key) + '" title="Move up"><i class="bi bi-arrow-up"></i></button>' +
                '<button type="button" class="sb-icon-btn" data-act="item-down" data-key="' + esc(key) + '" title="Move down"><i class="bi bi-arrow-down"></i></button>' +
                '<button type="button" class="sb-icon-btn" data-act="item-edit" data-key="' + esc(key) + '" title="Rename / change icon"><i class="bi bi-pencil"></i></button>' +
                '<button type="button" class="sb-icon-btn danger" data-act="item-hide" data-key="' + esc(key) + '" title="Remove from sidebar"><i class="bi bi-x-lg"></i></button>';
        }

        function renderAvailable() {
            const host = document.getElementById('sbAvailableList');
            const term = searchTerm.toLowerCase();
            let shown = 0;
            const html = LINKS.map(function (link) {
                const item = itemByKey(link.key);
                const label = (item && item.label) || link.label;
                if (term && label.toLowerCase().indexOf(term) < 0 && link.label.toLowerCase().indexOf(term) < 0) {
                    return '';
                }
                shown += 1;
                let badge = '<span class="sb-chip off">Not in sidebar</span>';
                if (item && !item.hidden) {
                    if (item.category) {
                        const cat = categoryByKey(item.category);
                        badge = '<span class="sb-chip on">' + esc(cat ? cat.name : item.category) + '</span>';
                    } else {
                        badge = '<span class="sb-chip on">Top level</span>';
                    }
                }
                return optionRow(item, { badge: badge });
            }).join('');
            host.innerHTML = html || '<div class="sb-empty">No option matches your search.</div>';
            document.getElementById('sbAvailableCount').textContent = String(shown);
        }

        function renderLayout() {
            const rootHost = document.getElementById('sbRootList');
            const rootItems = bucketItems('__root');
            rootHost.innerHTML = rootItems.length
                ? rootItems.map(function (i) { return optionRow(i, { actions: itemActions(i.key) }); }).join('')
                : '<div class="sb-empty">Drag options here to show them above the categories.</div>';
            document.getElementById('sbRootCount').textContent = String(rootItems.length);

            const catHost = document.getElementById('sbCategoryList');
            catHost.innerHTML = layout.categories.map(function (cat) {
                const items = bucketItems(cat.key);
                const body = items.length
                    ? items.map(function (i) { return optionRow(i, { actions: itemActions(i.key) }); }).join('')
                    : '<div class="sb-empty">Drop sidebar options here.</div>';
                return '' +
                    '<div class="sb-cat' + (cat.is_active ? '' : ' is-off') + '" draggable="true" data-kind="cat" data-key="' + esc(cat.key) + '"' +
                        ' data-drop="cat" data-cat="' + esc(cat.key) + '">' +
                        '<div class="sb-cat-head">' +
                            '<i class="bi bi-grip-vertical sb-grip"></i>' +
                            '<i class="bi ' + esc(iconClass(cat.icon, DEFAULT_ICON)) + ' text-warning"></i>' +
                            '<span class="sb-cat-title">' + esc(cat.name) + '</span>' +
                            '<span class="badge bg-secondary">' + items.length + '</span>' +
                            '<button type="button" class="sb-icon-btn" data-act="cat-up" data-key="' + esc(cat.key) + '" title="Move category up"><i class="bi bi-arrow-up"></i></button>' +
                            '<button type="button" class="sb-icon-btn" data-act="cat-down" data-key="' + esc(cat.key) + '" title="Move category down"><i class="bi bi-arrow-down"></i></button>' +
                            '<button type="button" class="sb-icon-btn" data-act="cat-edit" data-key="' + esc(cat.key) + '" title="Rename / change icon"><i class="bi bi-pencil"></i></button>' +
                            '<button type="button" class="sb-icon-btn" data-act="cat-toggle" data-key="' + esc(cat.key) + '" title="' + (cat.is_active ? 'Hide this category' : 'Show this category') + '"><i class="bi ' + (cat.is_active ? 'bi-eye' : 'bi-eye-slash') + '"></i></button>' +
                            '<button type="button" class="sb-icon-btn danger" data-act="cat-delete" data-key="' + esc(cat.key) + '" title="Delete category"><i class="bi bi-trash"></i></button>' +
                        '</div>' +
                        '<div class="sb-drop">' + body + '</div>' +
                    '</div>';
            }).join('');
            document.getElementById('sbNoCategories').style.display = layout.categories.length ? 'none' : 'block';
        }

        function render() {
            renderAvailable();
            renderLayout();
        }

        // ------------------------------------------------------------------
        // moving items / categories
        // ------------------------------------------------------------------
        function placeItem(key, targetBucket, beforeKey) {
            const item = itemByKey(key);
            if (!item) { return false; }
            if (targetBucket === '__hidden') {
                if (item.hidden) { return false; }
                item.hidden = true;
                item.category = null;
                return true;
            }
            const category = (targetBucket === '__root') ? null : targetBucket;
            const others = layout.items.filter(function (i) { return i.key !== key; });
            let insertAt = -1;
            if (beforeKey) {
                for (let i = 0; i < others.length; i += 1) {
                    if (others[i].key === beforeKey) { insertAt = i; break; }
                }
            }
            if (insertAt < 0) {
                const wanted = category || '__root';
                for (let i = 0; i < others.length; i += 1) {
                    const other = others[i];
                    if (other.hidden) { continue; }
                    if ((other.category || '__root') === wanted) { insertAt = i + 1; }
                }
            }
            item.hidden = false;
            item.category = category;
            layout.items = others;
            if (insertAt < 0) { insertAt = others.length; }
            layout.items.splice(insertAt, 0, item);
            return true;
        }

        function moveWithin(key, delta) {
            const item = itemByKey(key);
            if (!item || item.hidden) { return false; }
            const siblings = bucketItems(item.category || '__root');
            const index = siblings.findIndex(function (i) { return i.key === key; });
            if (index < 0) { return false; }
            const target = siblings[index + delta];
            if (!target) { return false; }
            if (delta < 0) {
                return placeItem(key, item.category || '__root', target.key);
            }
            return placeItemAfter(key, target.key);
        }

        function placeItemAfter(key, afterKey) {
            const item = itemByKey(key);
            const others = layout.items.filter(function (i) { return i.key !== key; });
            let at = others.findIndex(function (i) { return i.key === afterKey; });
            if (at < 0) { return false; }
            at += 1;
            layout.items = others;
            layout.items.splice(at, 0, item);
            return true;
        }

        function moveCategory(key, delta) {
            const index = layout.categories.findIndex(function (c) { return c.key === key; });
            if (index < 0) { return false; }
            const target = index + delta;
            if (target < 0 || target >= layout.categories.length) { return false; }
            const moved = layout.categories.splice(index, 1)[0];
            layout.categories.splice(target, 0, moved);
            return true;
        }

        function deleteCategory(key) {
            layout.categories = layout.categories.filter(function (c) { return c.key !== key; });
            layout.items.forEach(function (i) {
                if (i.category === key) {
                    i.category = null;
                    i.hidden = true;
                }
            });
        }

        // ------------------------------------------------------------------
        // drag & drop
        // ------------------------------------------------------------------
        function clearHighlights() {
            document.querySelectorAll('.drop-active').forEach(function (el) { el.classList.remove('drop-active'); });
            document.querySelectorAll('.dragging').forEach(function (el) { el.classList.remove('dragging'); });
        }

        function dropZoneFromEvent(event) {
            if (!event.target || !event.target.closest) { return null; }
            return event.target.closest('[data-drop]');
        }

        document.addEventListener('dragstart', function (event) {
            const handle = event.target.closest ? event.target.closest('[data-kind]') : null;
            if (!handle) { return; }
            dragState = { kind: handle.getAttribute('data-kind'), key: handle.getAttribute('data-key') };
            handle.classList.add('dragging');
            try {
                event.dataTransfer.effectAllowed = 'move';
                event.dataTransfer.setData('text/plain', dragState.key);
            } catch (err) { /* older browsers */ }
        });

        document.addEventListener('dragend', function () {
            dragState = null;
            clearHighlights();
        });

        document.addEventListener('dragover', function (event) {
            if (!dragState) { return; }
            const zone = dropZoneFromEvent(event);
            if (!zone) { return; }
            const dropKind = zone.getAttribute('data-drop');
            if (dragState.kind === 'cat' && dropKind !== 'cat') { return; }
            event.preventDefault();
            try { event.dataTransfer.dropEffect = 'move'; } catch (err) { /* ignore */ }
            if (!zone.classList.contains('drop-active')) {
                clearHighlights();
                zone.classList.add('drop-active');
            }
        });

        document.addEventListener('dragleave', function (event) {
            const zone = dropZoneFromEvent(event);
            if (!zone) { return; }
            if (event.relatedTarget && zone.contains(event.relatedTarget)) { return; }
            zone.classList.remove('drop-active');
        });

        function beforeKeyAt(zone, y) {
            const rows = Array.prototype.slice.call(zone.querySelectorAll('.sb-option'));
            for (let i = 0; i < rows.length; i += 1) {
                const rect = rows[i].getBoundingClientRect();
                if (y < rect.top + (rect.height / 2)) {
                    return rows[i].getAttribute('data-key');
                }
            }
            return null;
        }

        document.addEventListener('drop', function (event) {
            if (!dragState) { return; }
            const zone = dropZoneFromEvent(event);
            clearHighlights();
            if (!zone) { dragState = null; return; }
            event.preventDefault();
            const kind = dragState.kind;
            const key = dragState.key;
            const dropKind = zone.getAttribute('data-drop');
            let changed = false;

            if (kind === 'cat') {
                const from = layout.categories.findIndex(function (c) { return c.key === key; });
                const toKey = zone.getAttribute('data-cat');
                const to = layout.categories.findIndex(function (c) { return c.key === toKey; });
                if (from >= 0 && to >= 0 && from !== to) {
                    const moved = layout.categories.splice(from, 1)[0];
                    layout.categories.splice(to, 0, moved);
                    changed = true;
                }
            } else if (dropKind === 'unassign') {
                changed = placeItem(key, '__hidden');
            } else if (dropKind === 'root') {
                changed = placeItem(key, '__root', beforeKeyAt(zone, event.clientY));
            } else if (dropKind === 'cat') {
                changed = placeItem(key, zone.getAttribute('data-cat'), beforeKeyAt(zone, event.clientY));
            }

            dragState = null;
            if (changed) {
                render();
                scheduleSave();
            }
        });

        // ------------------------------------------------------------------
        // buttons
        // ------------------------------------------------------------------
        document.addEventListener('click', function (event) {
            const btn = event.target.closest ? event.target.closest('[data-act]') : null;
            if (!btn) { return; }
            const act = btn.getAttribute('data-act');
            const key = btn.getAttribute('data-key');
            let changed = false;

            if (act === 'item-up' || act === 'item-down') {
                changed = moveWithin(key, act === 'item-up' ? -1 : 1);
            } else if (act === 'item-hide') {
                changed = placeItem(key, '__hidden');
            } else if (act === 'item-edit') {
                openItemModal(key);
                return;
            } else if (act === 'cat-up' || act === 'cat-down') {
                changed = moveCategory(key, act === 'cat-up' ? -1 : 1);
            } else if (act === 'cat-toggle') {
                const cat = categoryByKey(key);
                if (cat) { cat.is_active = !cat.is_active; changed = true; }
            } else if (act === 'cat-edit') {
                openCategoryModal(key);
                return;
            } else if (act === 'cat-delete') {
                const cat = categoryByKey(key);
                if (!cat) { return; }
                const count = bucketItems(key).length;
                const message = 'Delete the category "' + cat.name + '"?\n\n' +
                    (count
                        ? count + ' option(s) inside it will be removed from the sidebar (they stay available in the left panel).'
                        : 'It is empty, so nothing else changes.');
                if (!window.confirm(message)) { return; }
                deleteCategory(key);
                changed = true;
            }

            if (changed) {
                render();
                scheduleSave();
            }
        });

        // ------------------------------------------------------------------
        // search
        // ------------------------------------------------------------------
        document.getElementById('sbSearch').addEventListener('input', function (event) {
            searchTerm = event.target.value || '';
            renderAvailable();
        });

        // ------------------------------------------------------------------
        // modals
        // ------------------------------------------------------------------
        let categoryModal = null;
        let itemModal = null;
        if (window.bootstrap) {
            categoryModal = new window.bootstrap.Modal(document.getElementById('sbCategoryModal'));
            itemModal = new window.bootstrap.Modal(document.getElementById('sbItemModal'));
        }

        function updateCategoryIconPreview() {
            const value = document.getElementById('sbCategoryIcon').value;
            document.getElementById('sbCategoryIconPreview').className = 'bi ' + iconClass(value, DEFAULT_ICON);
        }
        function updateItemIconPreview() {
            const value = document.getElementById('sbItemIcon').value;
            document.getElementById('sbItemIconPreview').className = 'bi ' + iconClass(value, 'bi-circle');
        }

        function openCategoryModal(key) {
            if (!categoryModal) { return; }
            editingCategoryKey = key || null;
            const cat = key ? categoryByKey(key) : null;
            document.getElementById('sbCategoryModalTitle').textContent = cat ? 'Edit category' : 'New category';
            document.getElementById('sbCategoryName').value = cat ? cat.name : '';
            document.getElementById('sbCategoryIcon').value = cat ? cat.icon : DEFAULT_ICON;
            updateCategoryIconPreview();
            categoryModal.show();
            setTimeout(function () { document.getElementById('sbCategoryName').focus(); }, 250);
        }

        function fillItemCategoryChoices(selected) {
            const select = document.getElementById('sbItemCategory');
            let html = '<option value="__hidden">Not in the sidebar</option>' +
                '<option value="__root">Top level (above the categories)</option>';
            layout.categories.forEach(function (cat) {
                html += '<option value="' + esc(cat.key) + '">' + esc(cat.name) + '</option>';
            });
            select.innerHTML = html;
            select.value = selected;
            if (!select.value) { select.value = '__root'; }
        }

        function openItemModal(key) {
            if (!itemModal) { return; }
            const item = itemByKey(key);
            const link = LINK_BY_KEY[key];
            if (!item || !link) { return; }
            editingItemKey = key;
            document.getElementById('sbItemModalTitle').textContent = 'Edit "' + (item.label || link.label) + '"';
            document.getElementById('sbItemLabel').value = item.label || link.label;
            document.getElementById('sbItemIcon').value = item.icon || '';
            document.getElementById('sbItemDefaultLabel').textContent = 'Built-in name: ' + link.label + ' · icon: ' + link.icon;
            fillItemCategoryChoices(item.hidden ? '__hidden' : (item.category || '__root'));
            updateItemIconPreview();
            itemModal.show();
            setTimeout(function () { document.getElementById('sbItemLabel').focus(); }, 250);
        }

        document.getElementById('sbCategoryIcon').addEventListener('input', updateCategoryIconPreview);
        document.getElementById('sbItemIcon').addEventListener('input', updateItemIconPreview);

        document.getElementById('sbAddCategory').addEventListener('click', function () { openCategoryModal(null); });

        document.getElementById('sbCategorySave').addEventListener('click', function () {
            const name = document.getElementById('sbCategoryName').value.trim();
            const nameEl = document.getElementById('sbCategoryName');
            if (!name) { nameEl.focus(); return; }
            const clash = layout.categories.some(function (c) {
                return c.key !== editingCategoryKey && c.name.trim().toLowerCase() === name.toLowerCase();
            });
            if (clash) {
                window.alert('A category named "' + name + '" already exists. Choose another name.');
                nameEl.focus();
                return;
            }
            const icon = iconClass(document.getElementById('sbCategoryIcon').value, DEFAULT_ICON);
            if (editingCategoryKey) {
                const cat = categoryByKey(editingCategoryKey);
                if (cat) { cat.name = name; cat.icon = icon; }
            } else {
                layout.categories.push({
                    key: newCategoryKey(),
                    name: name,
                    icon: icon,
                    is_active: true
                });
            }
            editingCategoryKey = null;
            if (categoryModal) { categoryModal.hide(); }
            render();
            scheduleSave();
        });

        function applyItemEdit(label, icon, targetBucket) {
            const item = itemByKey(editingItemKey);
            if (!item) { return; }
            const link = LINK_BY_KEY[editingItemKey];
            const cleanLabel = (label || '').trim();
            item.label = (!cleanLabel || cleanLabel === link.label) ? null : cleanLabel;
            item.icon = icon ? iconClass(icon, link.icon) : null;
            if (targetBucket) {
                const currentBucket = item.hidden ? '__hidden' : (item.category || '__root');
                if (targetBucket !== currentBucket) {
                    placeItem(editingItemKey, targetBucket, null);
                }
            }
            editingItemKey = null;
            if (itemModal) { itemModal.hide(); }
            render();
            scheduleSave();
        }

        document.getElementById('sbItemSave').addEventListener('click', function () {
            applyItemEdit(
                document.getElementById('sbItemLabel').value,
                document.getElementById('sbItemIcon').value,
                document.getElementById('sbItemCategory').value
            );
        });
        document.getElementById('sbItemReset').addEventListener('click', function () {
            const bucket = document.getElementById('sbItemCategory').value;
            applyItemEdit('', '', bucket);
        });

        // ------------------------------------------------------------------
        // reset
        // ------------------------------------------------------------------
        document.getElementById('sbReset').addEventListener('click', function () {
            if (!window.confirm('Reset the sidebar to the default layout?\n\nYour custom categories, names, icons and ordering will be lost.')) {
                return;
            }
            fetch(RESET_URL, { method: 'POST' }).then(function (resp) {
                return resp.json().then(function (data) { return { ok: resp.ok, data: data }; });
            }).then(function (res) {
                if (res.ok && res.data && res.data.layout) {
                    layout = normalize(res.data.layout);
                    render();
                    setStatus('Default layout restored', 'bg-success text-dark');
                } else {
                    window.alert((res.data && res.data.error) || 'The sidebar could not be reset.');
                }
            }).catch(function () {
                window.alert('Could not reach the server — nothing was reset.');
            });
        });

        render();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
