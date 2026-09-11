import "@testing-library/jest-dom/vitest";

// jsdom lacks these; the console only uses them through optional chaining but
// some components (range inputs, clipboard) probe them defensively.
if (typeof window !== "undefined") {
  if (!window.matchMedia) {
    // @ts-expect-error - test shim
    window.matchMedia = () => ({
      matches: false,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      addListener: () => undefined,
      removeListener: () => undefined,
      dispatchEvent: () => false,
    });
  }
}
