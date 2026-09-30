# Conservative silkscreen profile

User approved on 2026-09-30: one prudent profile referencing JLCPCB/PCBWay,
post-clipping small-feature diagnostics and a calibration fixture. No supplier
order or automatic geometry removal is authorized.

Implement a default CLI profile: minimum target stroke0.20mm, mask/drill
clearance0.25mm, text height guidance1.0mm. Preserve stricter input clearance.
An explicit geometry-only option preserves the previous geometry behavior.
Library callers opt in to the profile; the CLI report exposes the effective
parameters and sources. This is an engineering recommendation, not a joint
supplier certification, and PCBWay mask clearance still requires confirmation.

Audit the union of serialized polygons, never individual triangles. A bounded
morphological heuristic identifies thin components and potential detail loss;
state its limitations, keep ink unchanged and return review-required warnings.
Text height cannot be checked from unlabelled geometry. An optional SVG marks
problem areas. Protect all artifact paths and stage preview/report before PCB
promotion. Retain prior output semantics and report partial promotion failures.

Add tests for effective/profile clearance, explicit bypass, post-clipping thin
features, union invariance, preview/path protection and calibration inputs.
Run actual KiCad exports on the public demo and calibration coupon. Store fresh
evidence without replacing prior cohorts. Document and inspect previews, then
independent review and one consolidated project-note update. No commit/push/order.
