-- 0009_receipt_terms_booking.sql
--
-- The first three terms of the reference Urdu receipt talk about a *booking*
-- (بکنگ) — the rate a buyer is quoted when material is booked — not a bank
-- (بینک).  0008 seeded those clauses with the wrong word, so correct exactly
-- those rows here and leave every other (admin-written) term untouched.
--
-- Only the wording changes: id, is_active and sort_order are kept, so an
-- admin's enabled/disabled choice and ordering survive.
--
-- Re-run safety: each UPDATE matches the old text exactly, so a second run
-- finds nothing to change.  Nothing is inserted or deleted — a database where
-- an admin removed a clause stays as the admin left it.

UPDATE terms_and_conditions
SET title = 'بکنگ کی مکمل ادائیگی',
    content_ur = 'بکنگ پر خریدار کو دیا گیا ریٹ صرف اسی صورت میں لاگو ہوگا جب وہ اس بکنگ کی پوری رقم ادا کرے۔'
WHERE content_ur = 'بینک پر خریدار کو دیا گیا ریٹ صرف اسی صورت میں لاگو ہوگا جب وہ اس بینک کی پوری رقم ادا کرے۔';

UPDATE terms_and_conditions
SET content_ur = 'اگر بکنگ کی رقم جزوی ادا کی جائے تو بکنگ کا ریٹ صرف ادا شدہ رقم کے مطابق مال پر لاگو ہوگا۔'
WHERE content_ur = 'اگر بینک کی رقم جزوی ادا کی جائے تو بینک کا ریٹ صرف ادا شدہ رقم کے مطابق مال پر لاگو ہوگا۔';

UPDATE terms_and_conditions
SET content_ur = 'بقیہ رقم/بکنگ کے بقیہ مال پر مارکیٹ کا نیا ریٹ لاگو ہوگا۔'
WHERE content_ur = 'بقیہ رقم/بینک کے بقیہ مال پر مارکیٹ کا نیا ریٹ لاگو ہوگا۔';
