# Module: Explainability

## Overview

A feature on the DiscoverAI search results page that helps a user (or someone
reviewing the project) understand not just *what* matched their query, but
*why* — both the raw mechanics behind a single result's score, and how that
result compares to the ones ranked near it.

## Functional Requirements

### FR1 — Explain how the score is calculated

For any given result, the user can see the raw parameters that produced its
match score, not just the final percentage. This includes at minimum:

- The search query text
- Which embedding mode was used (Full Details / By Name / By Category)
- The raw cosine distance value returned by the database
- The formula used to turn that distance into the displayed similarity %
  (`similarity % = (1 - cosine distance) × 100`)
- The actual text that was embedded for this product (e.g. for Full Details:
  name + description + brand + category + price + attributes combined) —
  so the user can see exactly what their query was compared against

### FR2 — Explain why one result outranks another

For a result at rank N+1, explain why it lost to the product directly above
it at rank N — a pairwise comparison against its immediate neighbor, not the
whole result set. **Confirmed.**

## UX Requirements

- The results page layout changes from the current grid to a single-column,
  mobile-style list — one product per row. This **replaces** the existing
  grid UI entirely (not a separate mode). **Confirmed.**
- Each row has an "Explainability" affordance on the right side of the row
  (icon or button).
- Clicking it opens the explainability detail as a **side panel** (slides in
  from the side, rather than expanding the row inline or opening a modal).
  **Confirmed.**

## Out of scope (for now, unless you say otherwise)

- Changing the underlying ranking/scoring algorithm itself — this module is
  about *explaining* the existing score, not changing how it's computed.
