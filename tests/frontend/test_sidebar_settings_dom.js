/* Offline DOM test for static/sidebar_settings.js (Settings → Sidebar Settings).
   Run:  npm i jsdom  (or NODE_PATH=/path/to/jsdom) then
         node tests/frontend/test_sidebar_settings_dom.js */
const fs = require("fs");
const path = require("path");
let JSDOM;
try { JSDOM = require("jsdom").JSDOM; }
catch (_) { JSDOM = require("/tmp/node_modules/jsdom").JSDOM; }

const code = fs.readFileSync(
    path.join(__dirname, "..", "..", "static", "sidebar_settings.js"),
    "utf8"
);

let pass = 0, fail = 0;
function check(name, cond) {
    if (cond) { pass++; console.log("  ok  -", name); }
    else { fail++; console.log("  FAIL-", name); }
}

const LINKS = [
    { key: "dashboard", label: "Dashboard", icon: "bi-speedometer2", href: "/", default_category: null, description: "Home." },
    { key: "stock_summary", label: "Stock Summary", icon: "bi-graph-up", href: "/stock", default_category: "inventory", description: "Stock." },
    { key: "history", label: "History", icon: "bi-clock-history", href: "/tracking", default_category: "inventory", description: "History." },
    { key: "cash_flow", label: "Cash Flow", icon: "bi-water", href: "/cash_flow", default_category: "accounts", description: "Cash." },
];

const LAYOUT = {
    categories: [
        { key: "inventory", name: "Inventory", icon: "bi-boxes", is_active: true },
        { key: "accounts", name: "Accounts", icon: "bi-calculator", is_active: true },
    ],
    items: [
        { key: "dashboard", category: null, hidden: false, label: null, icon: null },
        { key: "stock_summary", category: "inventory", hidden: false, label: null, icon: null },
        { key: "history", category: "inventory", hidden: false, label: null, icon: null },
        { key: "cash_flow", category: "accounts", hidden: false, label: null, icon: null },
    ],
};

function fixture() {
    return `<!doctype html><html><body>
    <span id="sbStatus">Not saved yet</span>
    <button id="sbReset" type="button"></button>
    <input id="sbSearch" type="search">
    <span id="sbAvailableCount"></span>
    <div id="sbAvailableDrop" data-drop="unassign"><div id="sbAvailableList"></div></div>
    <button id="sbAddCategory" type="button"></button>
    <span id="sbRootCount"></span>
    <div id="sbRootList"></div>
    <div id="sbCategoryList"></div>
    <div id="sbNoCategories"></div>

    <div id="sbCategoryModal" class="modal">
        <h6 id="sbCategoryModalTitle"></h6>
        <input id="sbCategoryName" type="text">
        <i id="sbCategoryIconPreview"></i>
        <input id="sbCategoryIcon" type="text">
        <button id="sbCategorySave" type="button"></button>
    </div>
    <div id="sbItemModal" class="modal">
        <h6 id="sbItemModalTitle"></h6>
        <input id="sbItemLabel" type="text">
        <small id="sbItemDefaultLabel"></small>
        <select id="sbItemCategory"></select>
        <i id="sbItemIconPreview"></i>
        <input id="sbItemIcon" type="text">
        <button id="sbItemSave" type="button"></button>
        <button id="sbItemReset" type="button"></button>
    </div>
    <script type="application/json" id="sbConfig">${JSON.stringify({
        links: LINKS,
        layout: LAYOUT,
        saveUrl: "/settings/sidebar/save",
        resetUrl: "/settings/sidebar/reset",
    })}</script>
    </body></html>`;
}

const dom = new JSDOM(fixture(), {
    url: "http://localhost/settings/sidebar",
    runScripts: "outside-only",
    pretendToBeVisual: true,
});
const w = dom.window;
const d = w.document;

// ---- stubs -----------------------------------------------------------------
const posted = [];
let alerts = [];
let confirms = true;
w.fetch = function (url, opts) {
    posted.push({ url: String(url), body: opts && opts.body ? JSON.parse(opts.body) : null });
    const isReset = String(url).indexOf("/reset") >= 0;
    const payload = isReset ? { ok: true, layout: LAYOUT } : { ok: true };
    return Promise.resolve({ ok: true, json: () => Promise.resolve(payload) });
};
w.alert = function (message) { alerts.push(String(message)); };
w.confirm = function () { return confirms; };
w.bootstrap = {
    Modal: function (el) {
        this.el = el;
        this.show = function () { el.classList.add("show"); };
        this.hide = function () { el.classList.remove("show"); };
    },
};

function lastSave() {
    for (let i = posted.length - 1; i >= 0; i -= 1) {
        if (posted[i].body) { return posted[i]; }
    }
    return null;
}
function itemRow(label) {
    return Array.from(d.querySelectorAll("#sbCategoryList .sb-option, #sbRootList .sb-option"))
        .find((el) => el.textContent.indexOf(label) >= 0);
}
function categoryCard(name) {
    return Array.from(d.querySelectorAll("#sbCategoryList .sb-cat"))
        .find((el) => el.textContent.indexOf(name) >= 0);
}
function click(el) {
    el.dispatchEvent(new w.MouseEvent("click", { bubbles: true, cancelable: true }));
}
function dragStart(el) {
    el.dispatchEvent(new w.Event("dragstart", { bubbles: true, cancelable: true }));
}
function dropOn(el, clientY) {
    const ev = new w.Event("drop", { bubbles: true, cancelable: true });
    ev.clientY = clientY || 0;
    el.dispatchEvent(ev);
}
function tick(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms || 350));
}

(async function run() {
    w.eval(code);
    await tick(40);
    if (!d.querySelector("#sbCategoryList .sb-cat")) {
        d.dispatchEvent(new w.Event("DOMContentLoaded"));
        await tick(40);
    }

    // ---- initial render ----------------------------------------------------
    check("every option is listed on the left", d.querySelectorAll("#sbAvailableList .sb-option").length === LINKS.length);
    check("categories are rendered", d.querySelectorAll("#sbCategoryList .sb-cat").length === 2);
    check("top level item rendered", d.querySelectorAll("#sbRootList .sb-option").length === 1);
    const availableStock = Array.from(d.querySelectorAll("#sbAvailableList .sb-option"))
        .find((el) => el.textContent.indexOf("Stock Summary") >= 0);
    check("option badge shows its category", availableStock.textContent.indexOf("Inventory") >= 0);

    // ---- drag an option into another category ------------------------------
    dragStart(itemRow("Stock Summary"));
    dropOn(categoryCard("Accounts"), 0);
    await tick();
    let payload = lastSave();
    let moved = payload.body.items.find((i) => i.key === "stock_summary");
    check("drag saves the new category", moved.category === "accounts");
    check("drag keeps the option visible", moved.hidden === false);
    check("status shows saved", d.getElementById("sbStatus").textContent.indexOf("saved") >= 0);

    // ---- remove an option from the sidebar ---------------------------------
    dragStart(itemRow("History"));
    dropOn(d.getElementById("sbAvailableDrop"), 0);
    await tick();
    payload = lastSave();
    check("dropping on the left panel hides the option",
        payload.body.items.find((i) => i.key === "history").hidden === true);

    // ---- reorder a category with the arrow buttons -------------------------
    click(categoryCard("Accounts").querySelector('[data-act="cat-up"]'));
    await tick();
    payload = lastSave();
    check("category order follows the arrow button",
        payload.body.categories.map((c) => c.name).join(",") === "Accounts,Inventory");

    // ---- add a category through the modal ----------------------------------
    click(d.getElementById("sbAddCategory"));
    check("add-category opens the dialog", d.getElementById("sbCategoryModal").classList.contains("show"));
    d.getElementById("sbCategoryName").value = "Yard Ops";
    d.getElementById("sbCategoryIcon").value = "bi-fire";
    click(d.getElementById("sbCategorySave"));
    await tick();
    payload = lastSave();
    const added = payload.body.categories.find((c) => c.name === "Yard Ops");
    check("new category is saved", !!added);
    check("new category uses the chosen icon", added && added.icon === "bi-fire");
    check("dialog closes after saving", !d.getElementById("sbCategoryModal").classList.contains("show"));

    // ---- duplicate category names are rejected -----------------------------
    alerts = [];
    click(d.getElementById("sbAddCategory"));
    d.getElementById("sbCategoryName").value = "yard ops";
    const before = posted.length;
    click(d.getElementById("sbCategorySave"));
    await tick(150);
    check("duplicate category name is refused", alerts.length === 1 && posted.length === before);

    // ---- edit an option: rename, new icon, move via the select -------------
    click(d.querySelector('[data-act="item-edit"][data-key="cash_flow"]'));
    check("option dialog opens", d.getElementById("sbItemModal").classList.contains("show"));
    check("option dialog preselects the category", d.getElementById("sbItemCategory").value === "accounts");
    d.getElementById("sbItemLabel").value = "Cash Position";
    d.getElementById("sbItemIcon").value = "bi-piggy-bank";
    d.getElementById("sbItemCategory").value = added.key;
    click(d.getElementById("sbItemSave"));
    await tick();
    payload = lastSave();
    const edited = payload.body.items.find((i) => i.key === "cash_flow");
    check("renamed option is saved", edited.label === "Cash Position");
    check("option icon override is saved", edited.icon === "bi-piggy-bank");
    check("option moved through the select", edited.category === added.key);

    // ---- delete a category (its options leave the sidebar) -----------------
    confirms = true;
    click(categoryCard("Inventory").querySelector('[data-act="cat-delete"]'));
    await tick();
    payload = lastSave();
    check("deleted category is gone", !payload.body.categories.some((c) => c.key === "inventory"));

    click(categoryCard("Yard Ops").querySelector('[data-act="cat-delete"]'));
    await tick();
    payload = lastSave();
    check("deleted category is gone", !payload.body.categories.some((c) => c.name === "Yard Ops"));
    check("options of a deleted category are hidden",
        payload.body.items.filter((i) => i.category === "cat_" && i.hidden === false).length === 0 &&
        payload.body.items.find((i) => i.key === "cash_flow").hidden === true);

    // ---- search filters the left panel -------------------------------------
    const search = d.getElementById("sbSearch");
    search.value = "cash";
    search.dispatchEvent(new w.Event("input", { bubbles: true }));
    check("search filters the option list",
        d.querySelectorAll("#sbAvailableList .sb-option").length === 1);

    // ---- reset -------------------------------------------------------------
    const resetCount = posted.length;
    click(d.getElementById("sbReset"));
    await tick();
    check("reset calls the reset endpoint",
        posted.length > resetCount && posted[posted.length - 1].url.indexOf("/reset") >= 0);
    check("reset restores the default categories",
        d.querySelectorAll("#sbCategoryList .sb-cat").length === LAYOUT.categories.length);

    console.log(`\n${pass} passed, ${fail} failed`);
    process.exit(fail ? 1 : 0);
})();
