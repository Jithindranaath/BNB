/**
 * The product name lives HERE and nowhere else (context.md §1).
 * To rename the product, change these values only. Never hardcode the name
 * anywhere else in the codebase.
 */
export const brand = {
  name: "proofstand",
  tagline:
    "An agent marketplace for BNB Chain where every agent carries a verifiable receipt trail.",
  primaryCta: "Try an agent — no wallet needed",
} as const;

export type Brand = typeof brand;
