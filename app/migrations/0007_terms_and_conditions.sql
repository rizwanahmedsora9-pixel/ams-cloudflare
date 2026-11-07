-- 0007_terms_and_conditions.sql
--
-- Terms and conditions that can be printed on Urdu sales receipts.  Admin
-- users manage them from Settings -> Terms & Conditions (add, edit, enable /
-- disable, reorder).  Only active rows are offered on the Urdu receipt
-- print/download dialog, and only the chosen ones are printed, so more terms
-- can be added later without touching any code.
--
-- Re-run safety: IF NOT EXISTS / INSERT OR IGNORE make this file idempotent.

CREATE TABLE IF NOT EXISTS terms_and_conditions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title VARCHAR(120) NOT NULL DEFAULT '',
    content_ur TEXT NOT NULL DEFAULT '',
    is_active BOOLEAN NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO terms_and_conditions (title, content_ur, is_active, sort_order) VALUES
('بل کی ادائیگی', 'بل کی مکمل رقم بل کی تاریخ سے وصولی کے وقت ادا کی جائے گی۔', 1, 1),
('واپسی کی شرط', 'فروخت شدہ سامان واپس نہیں لیا جائے گا اور نہ رقم واپس کی جائے گی، جب تک کہ سامان إرسال کے وقت خراب نہ ہو۔', 1, 2),
('قانونی دائرہ کار', 'تمام اختلافات یا تنازعات کا فیصلہ گجرات، پنجاب کی متعلقہ عدالت کے تحت ہوگا۔', 1, 3);
