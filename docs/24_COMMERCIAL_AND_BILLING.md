# Commercial, Pricing and Billing Operations

Lifecycle: estimate → proposal snapshot → signed contract → milestone schedule → invoice → manual payment entry/reconciliation → overdue/dispute/refund record → final handover.

Store monetary values as integer minor units with ISO currency. Preserve signed proposal/contract snapshots; do not mutate historical commercial terms when catalog pricing changes. Track estimated vs actual time/cost, third-party costs, margin, revisions, support scope and hosting resource cost.

GST/SAC/PAN/Udyam/tax fields from legacy documents are placeholders; obtain CA review before live invoices or tax statements. Payment gateway adapters are optional; manual reconciliation first. Any charge, refund, campaign spend or paid infrastructure requires explicit approval.
