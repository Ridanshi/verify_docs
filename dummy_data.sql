-- Dummy test data — uses existing cloned records, no INSERTs needed.
-- Picks 3 real disbursements that have complete join data, assigns them
-- known test LANs and sets pending_approval_role = 'operations'.
--
-- After running, query the verification block at the bottom to see
-- what customer_name/bank/amounts were assigned — use those to build test documents.

BEGIN;

-- Pick 3 disbursements with complete joins and update to test values
WITH candidates AS (
    SELECT d.id, ROW_NUMBER() OVER (ORDER BY d.id) AS rn
    FROM disbursements d
    JOIN applications a    ON d.application_id    = a.id
    JOIN leads l           ON a.lead_id           = l.id
    JOIN lending_partners lp ON a.lending_partner_id = lp.id
    WHERE d.loan_account_number IS NOT NULL
    LIMIT 3
)
UPDATE disbursements d
SET
    loan_account_number   = CASE c.rn
                                WHEN 1 THEN 'TESTLAN000001'
                                WHEN 2 THEN 'TESTLAN000002'
                                WHEN 3 THEN 'TESTLAN000003'
                            END,
    pending_approval_role = 'operations',
    updated_at            = NOW()
FROM candidates c
WHERE d.id = c.id;

COMMIT;

-- Run this after to see what values the 3 test records have:
SELECT
    d.loan_account_number,
    l.name                          AS customer_name,
    lp.name                         AS bank_name,
    a.branch_name                   AS branch,
    a.bank_application_id           AS application_id,
    a.sanctioned_amount  / 100      AS sanction_amount_rupees,
    d.disbursement_amount / 100     AS disbursement_amount_rupees,
    d.disbursement_date
FROM disbursements d
JOIN applications    a  ON d.application_id    = a.id
JOIN leads           l  ON a.lead_id           = l.id
JOIN lending_partners lp ON a.lending_partner_id = lp.id
WHERE d.loan_account_number IN ('TESTLAN000001', 'TESTLAN000002', 'TESTLAN000003');
