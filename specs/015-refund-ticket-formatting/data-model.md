# Phase 1 Data Model: Refund Ticket Formatting Fix

No new or modified entities. This feature is a rendering/formatting fix only.

The **Refund Ticket** entity (fields: `order_id`, `issue`, `sentiment`, `refund_created`) is
unchanged in shape, content, and source from
[specs/011-ticket-markdown-generation/data-model.md](../011-ticket-markdown-generation/data-model.md).
The dict passed into `write_refund_ticket()` / `_render_refund_ticket()` keeps the same keys and
semantics; only the markdown string produced from it changes (bold label + plain value per
field, instead of the whole field line in bold).

No database schema, `SupportState` fields, or file-naming scheme are affected.
