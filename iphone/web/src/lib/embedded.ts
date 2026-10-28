// HydraNest: true when this UI is framed in HydraNest's iPhone page, which
// draws the header and sidebar and handles the sign-in.
export const embedded: boolean = (() => {
  try {
    return window.self !== window.top;
  } catch {
    return true; // a cross-origin parent: framed all the same
  }
})();
