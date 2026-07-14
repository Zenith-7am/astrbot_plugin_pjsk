// Render function registry — loaded once at service startup into canvas_page.
// Each render JS file calls registerRenderFunction(name, fn) to register.

window.__renderFunctions = {};

window.registerRenderFunction = function(name, fn) {
  window.__renderFunctions[name] = fn;
  console.log('[render-service] registered function:', name);
};
